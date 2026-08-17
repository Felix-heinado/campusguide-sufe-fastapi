"""Shared persistence contracts and task data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


@dataclass(slots=True)
class TaskRecord:
    """One asynchronous ingestion task.

    The explicit fields make the task state machine easy to inspect during an
    interview. A task moves through: queued -> running -> succeeded/failed.
    """

    task_id: str
    source: str
    idempotency_key: str | None
    kind: str
    status: str = "queued"
    attempts: int = 0
    retry_count: int = 0
    max_attempts: int = 2
    recovered_after_restart: bool = False
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        """Convert datetimes to JSON-friendly ISO strings for API responses."""

        value = asdict(self)
        for key in ("lease_expires_at", "created_at", "updated_at"):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        return value


@dataclass(slots=True)
class MessageRecord:
    """One user, assistant, or tool message in a conversation."""

    message_id: str
    session_id: str
    role: str
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["created_at"] = self.created_at.isoformat()
        return value


@dataclass(slots=True)
class AgentRunRecord:
    """Persistent summary of one Agent execution."""

    run_id: str
    session_id: str
    status: str = "running"
    step_count: int = 0
    answer: str | None = None
    error: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["started_at"] = self.started_at.isoformat()
        if self.finished_at:
            value["finished_at"] = self.finished_at.isoformat()
        return value


@dataclass(slots=True)
class ToolCallRecord:
    """Audit record for a tool call made during an Agent run."""

    call_id: str
    run_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    duration_ms: float = 0
    created_at: datetime = field(default_factory=utc_now)


class Repository(Protocol):
    """Operations needed by feedback and the asynchronous task service."""

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def insert_feedback(self, row: dict[str, Any]) -> None: ...

    async def create_or_get_task(self, candidate: TaskRecord) -> tuple[TaskRecord, bool]: ...

    async def claim_task(
        self, task_id: str, worker_id: str, lease_seconds: int
    ) -> TaskRecord | None: ...

    async def save_task(self, task: TaskRecord, worker_id: str) -> None: ...

    async def get_task(self, task_id: str) -> TaskRecord | None: ...

    async def recover_expired_tasks(self) -> list[TaskRecord]: ...

    async def create_session(self, session_id: str, title: str) -> dict[str, Any]: ...

    async def get_session(self, session_id: str) -> dict[str, Any] | None: ...

    async def add_message(self, message: MessageRecord) -> None: ...

    async def list_messages(self, session_id: str, limit: int) -> list[MessageRecord]: ...

    async def create_agent_run(self, run: AgentRunRecord) -> None: ...

    async def save_agent_run(self, run: AgentRunRecord) -> None: ...

    async def save_tool_call(self, call: ToolCallRecord) -> None: ...
