"""Small JSON repository used for offline study and automated tests.

The lock serializes read-modify-write operations inside one process. Writing a
temporary file and replacing the target prevents a crash from leaving a
half-written JSON document. MySQL should be used for multi-process deployment.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .base import AgentRunRecord, MessageRecord, TaskRecord, ToolCallRecord


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _task_from_dict(row: dict[str, Any]) -> TaskRecord:
    return TaskRecord(
        task_id=row["task_id"], source=row["source"],
        idempotency_key=row.get("idempotency_key"), kind=row["kind"],
        status=row.get("status", "queued"), attempts=row.get("attempts", 0),
        retry_count=row.get("retry_count", 0), max_attempts=row.get("max_attempts", 2),
        recovered_after_restart=row.get("recovered_after_restart", False),
        result=row.get("result"), error=row.get("error"), worker_id=row.get("worker_id"),
        lease_expires_at=_parse_datetime(row.get("lease_expires_at")),
        created_at=_parse_datetime(row.get("created_at")) or datetime.now(UTC),
        updated_at=_parse_datetime(row.get("updated_at")) or datetime.now(UTC),
    )


class JsonRepository:
    """Dependency-free repository with the same behavior as the MySQL adapter."""

    def __init__(
        self,
        feedback_path: Path,
        task_path: Path,
        agent_state_path: Path | None = None,
    ) -> None:
        self.feedback_path = feedback_path
        self.task_path = task_path
        self.agent_state_path = agent_state_path or task_path.with_name("agent_state.json")
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self.feedback_path.parent.mkdir(parents=True, exist_ok=True)

    async def close(self) -> None:
        return None

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as file:
            value = json.load(file)
        if not isinstance(value, list):
            raise ValueError(f"{path.name} must contain a JSON array")
        return value

    @staticmethod
    def _write(path: Path, rows: list[dict[str, Any]]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(rows, file, ensure_ascii=False, indent=2)
            file.flush()
        temporary.replace(path)

    async def insert_feedback(self, row: dict[str, Any]) -> None:
        async with self._lock:
            rows = self._read(self.feedback_path)
            rows.append({**row, "created_at": row["created_at"].isoformat()})
            self._write(self.feedback_path, rows[-1000:])

    async def create_or_get_task(self, candidate: TaskRecord) -> tuple[TaskRecord, bool]:
        async with self._lock:
            tasks = [_task_from_dict(row) for row in self._read(self.task_path)]
            if candidate.idempotency_key:
                existing = next(
                    (task for task in tasks if task.idempotency_key == candidate.idempotency_key),
                    None,
                )
                if existing:
                    return existing, False
            tasks.append(candidate)
            self._write(self.task_path, [task.to_dict() for task in tasks])
            return candidate, True

    async def claim_task(
        self, task_id: str, worker_id: str, lease_seconds: int
    ) -> TaskRecord | None:
        async with self._lock:
            tasks = [_task_from_dict(row) for row in self._read(self.task_path)]
            task = next((item for item in tasks if item.task_id == task_id), None)
            if not task or task.status != "queued" or task.attempts >= task.max_attempts:
                return None
            task.status = "running"
            task.attempts += 1
            task.worker_id = worker_id
            task.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
            task.updated_at = datetime.now(UTC)
            self._write(self.task_path, [item.to_dict() for item in tasks])
            return task

    async def save_task(self, task: TaskRecord, worker_id: str) -> None:
        async with self._lock:
            tasks = [_task_from_dict(row) for row in self._read(self.task_path)]
            stored = next((item for item in tasks if item.task_id == task.task_id), None)
            if not stored or stored.worker_id != worker_id:
                return
            task.worker_id = None
            task.lease_expires_at = None
            task.updated_at = datetime.now(UTC)
            tasks[tasks.index(stored)] = task
            self._write(self.task_path, [item.to_dict() for item in tasks])

    async def get_task(self, task_id: str) -> TaskRecord | None:
        async with self._lock:
            return next(
                (
                    _task_from_dict(row)
                    for row in self._read(self.task_path)
                    if row["task_id"] == task_id
                ),
                None,
            )

    async def recover_expired_tasks(self) -> list[TaskRecord]:
        async with self._lock:
            now = datetime.now(UTC)
            tasks = [_task_from_dict(row) for row in self._read(self.task_path)]
            for task in tasks:
                if (
                    task.status == "running" and task.lease_expires_at
                    and task.lease_expires_at < now and task.attempts < task.max_attempts
                ):
                    task.status = "queued"
                    task.recovered_after_restart = True
                    task.worker_id = None
                    task.lease_expires_at = None
                    task.updated_at = now
            self._write(self.task_path, [task.to_dict() for task in tasks])
            return [task for task in tasks if task.status == "queued"]

    def _read_agent_state(self) -> dict[str, list[dict[str, Any]]]:
        """Read conversation state with an explicit, inspectable JSON shape."""

        if not self.agent_state_path.exists():
            return {"sessions": [], "messages": [], "runs": [], "tool_calls": []}
        with self.agent_state_path.open("r", encoding="utf-8") as file:
            state = json.load(file)
        required = {"sessions", "messages", "runs", "tool_calls"}
        if not isinstance(state, dict) or not required.issubset(state):
            raise ValueError("agent_state.json has an invalid structure")
        return state

    async def create_session(self, session_id: str, title: str) -> dict[str, Any]:
        async with self._lock:
            state = self._read_agent_state()
            now = datetime.now(UTC).isoformat()
            session = {
                "session_id": session_id,
                "title": title,
                "created_at": now,
                "updated_at": now,
            }
            state["sessions"].append(session)
            self._write_agent_state(state)
            return session

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            state = self._read_agent_state()
            return next(
                (item for item in state["sessions"] if item["session_id"] == session_id),
                None,
            )

    async def add_message(self, message: MessageRecord) -> None:
        async with self._lock:
            state = self._read_agent_state()
            state["messages"].append(message.to_dict())
            for session in state["sessions"]:
                if session["session_id"] == message.session_id:
                    session["updated_at"] = message.created_at.isoformat()
            self._write_agent_state(state)

    async def list_messages(self, session_id: str, limit: int) -> list[MessageRecord]:
        async with self._lock:
            state = self._read_agent_state()
            rows = [
                row for row in state["messages"] if row["session_id"] == session_id
            ][-limit:]
            return [
                MessageRecord(
                    message_id=row["message_id"],
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    tool_name=row.get("tool_name"),
                    tool_call_id=row.get("tool_call_id"),
                    created_at=_parse_datetime(row["created_at"]) or datetime.now(UTC),
                )
                for row in rows
            ]

    async def create_agent_run(self, run: AgentRunRecord) -> None:
        async with self._lock:
            state = self._read_agent_state()
            state["runs"].append(run.to_dict())
            self._write_agent_state(state)

    async def save_agent_run(self, run: AgentRunRecord) -> None:
        async with self._lock:
            state = self._read_agent_state()
            for index, stored in enumerate(state["runs"]):
                if stored["run_id"] == run.run_id:
                    state["runs"][index] = run.to_dict()
                    break
            self._write_agent_state(state)

    async def save_tool_call(self, call: ToolCallRecord) -> None:
        async with self._lock:
            state = self._read_agent_state()
            row = {
                "call_id": call.call_id,
                "run_id": call.run_id,
                "tool_name": call.tool_name,
                "arguments": call.arguments,
                "status": call.status,
                "result": call.result,
                "error": call.error,
                "duration_ms": call.duration_ms,
                "created_at": call.created_at.isoformat(),
            }
            state["tool_calls"].append(row)
            self._write_agent_state(state)

    def _write_agent_state(self, state: dict[str, list[dict[str, Any]]]) -> None:
        temporary = self.agent_state_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
            file.flush()
        temporary.replace(self.agent_state_path)
