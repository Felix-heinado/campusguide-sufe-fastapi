"""Readable MySQL persistence using a small async connection pool.

SQL is kept next to the operation that uses it. This is more verbose than an
ORM, but it lets a student directly explain transactions, unique constraints,
row locks, and parameterized queries during an interview.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from ..config import Settings
from .base import AgentRunRecord, MessageRecord, TaskRecord, ToolCallRecord


def _as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to MySQL DATETIME values, which are returned without a zone."""

    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def _decode_json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _task_from_row(row: dict[str, Any]) -> TaskRecord:
    """Translate a database row into the type used by business services."""

    return TaskRecord(
        task_id=row["task_id"],
        source=row["source"],
        idempotency_key=row["idempotency_key"],
        kind=row["kind"],
        status=row["status"],
        attempts=row["attempts"],
        retry_count=row["retry_count"],
        max_attempts=row["max_attempts"],
        recovered_after_restart=bool(row["recovered_after_restart"]),
        result=_decode_json(row["result"]),
        error=_decode_json(row["error"]),
        worker_id=row["worker_id"],
        lease_expires_at=_as_utc(row["lease_expires_at"]),
        created_at=_as_utc(row["created_at"]),
        updated_at=_as_utc(row["updated_at"]),
    )


class MySQLRepository:
    """MySQL adapter for multi-request and multi-worker execution."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pool: Any = None

    async def start(self) -> None:
        """Create the pool lazily so importing the application has no side effect."""

        try:
            import aiomysql
        except ImportError as error:  # pragma: no cover - depends on local extras
            raise RuntimeError("install the 'mysql' extra to use MySQL") from error

        self.pool = await aiomysql.create_pool(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password,
            db=self.settings.mysql_database,
            minsize=self.settings.mysql_pool_min_size,
            maxsize=self.settings.mysql_pool_max_size,
            autocommit=False,
            cursorclass=aiomysql.DictCursor,
        )

    async def close(self) -> None:
        if self.pool is not None:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None

    async def health_check(self) -> dict[str, Any]:
        if self.pool is None:
            return {"status": "down", "backend": "mysql", "persistent": False}
        try:
            row = await self._execute_for_result("SELECT 1 AS ok", ())
            return {
                "status": "ok" if row and row.get("ok") == 1 else "degraded",
                "backend": "mysql", "persistent": True,
            }
        except Exception:
            return {"status": "down", "backend": "mysql", "persistent": False}

    async def record_search_event(self, row: dict[str, Any]) -> None:
        sql = """
            INSERT INTO agent_search_events
                (event_id, request_id, query_hash, query_length, result_count,
                 top_document_id, retrieval_mode, duration_ms, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        await self._execute(sql, (
            row["event_id"], row["request_id"], row["query_hash"],
            row["query_length"], row["result_count"], row.get("top_document_id"),
            row.get("retrieval_mode"), row.get("duration_ms", 0), row["created_at"],
        ))

    async def operational_stats(self) -> dict[str, Any]:
        queries = {
            "searchEvents": "SELECT COUNT(*) AS count FROM agent_search_events",
            "feedback": "SELECT COUNT(*) AS count FROM feedback",
            "ingestionTasks": "SELECT COUNT(*) AS count FROM ingestion_tasks",
            "agentRuns": "SELECT COUNT(*) AS count FROM agent_runs",
        }
        result: dict[str, Any] = {}
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                for key, sql in queries.items():
                    await cursor.execute(sql)
                    row = await cursor.fetchone()
                    result[key] = int(row["count"])
        return result

    async def _execute(self, sql: str, params: tuple) -> None:
        """Execute a write query and commit inside a pooled connection."""

        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, params)
            await connection.commit()

    async def _execute_for_result(
        self, sql: str, params: tuple
    ) -> dict[str, Any] | None:
        """Execute a read query inside a pooled connection and return one row."""

        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, params)
                return await cursor.fetchone()

    async def insert_feedback(self, row: dict[str, Any]) -> None:
        """Store feedback with a unique public ID and a searchable question hash."""

        sql = """
            INSERT INTO feedback
                (feedback_id, question_hash, helpful, reasons, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """
        await self._execute(
            sql,
            (
                row["feedback_id"], row["question_hash"], row["helpful"],
                json.dumps(row["reasons"], ensure_ascii=False), row["created_at"],
            ),
        )

    async def create_or_get_task(self, candidate: TaskRecord) -> tuple[TaskRecord, bool]:
        """Atomically implement idempotency with a unique database key.

        Two concurrent requests may carry the same idempotency key. The unique
        index lets MySQL choose one row; both callers then read the same task.
        This avoids the race created by "SELECT first, INSERT later".
        """

        insert_sql = """
            INSERT INTO ingestion_tasks
                (task_id, source, idempotency_key, kind, status, attempts,
                 retry_count, max_attempts, recovered_after_restart,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'queued', 0, 0, %s, 0, %s, %s)
            ON DUPLICATE KEY UPDATE task_id = task_id
        """
        lookup_sql = """
            SELECT * FROM ingestion_tasks
            WHERE task_id = %s OR idempotency_key = %s
            LIMIT 1
        """
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                affected = await cursor.execute(insert_sql, (
                    candidate.task_id, candidate.source, candidate.idempotency_key,
                    candidate.kind, candidate.max_attempts, candidate.created_at,
                    candidate.updated_at,
                ))
                await cursor.execute(lookup_sql, (
                    candidate.task_id, candidate.idempotency_key,
                ))
                row = await cursor.fetchone()
            await connection.commit()
        return _task_from_row(row), affected == 1

    async def claim_task(
        self, task_id: str, worker_id: str, lease_seconds: int
    ) -> TaskRecord | None:
        """Claim one queued task inside a transaction.

        ``FOR UPDATE`` prevents two workers from claiming the same existing
        task row. The lease makes a crashed worker's task recoverable later.
        """

        select_sql = "SELECT * FROM ingestion_tasks WHERE task_id = %s FOR UPDATE"
        update_sql = """
            UPDATE ingestion_tasks
            SET status = 'running', attempts = attempts + 1,
                worker_id = %s, lease_expires_at = %s, updated_at = %s
            WHERE task_id = %s
        """
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=lease_seconds)
        async with self.pool.acquire() as connection:
            try:
                await connection.begin()
                async with connection.cursor() as cursor:
                    await cursor.execute(select_sql, (task_id,))
                    row = await cursor.fetchone()
                    cannot_claim = (
                        not row
                        or row["status"] != "queued"
                        or row["attempts"] >= row["max_attempts"]
                    )
                    if cannot_claim:
                        await connection.rollback()
                        return None
                    await cursor.execute(update_sql, (worker_id, lease_until, now, task_id))
                    await cursor.execute(select_sql, (task_id,))
                    claimed = await cursor.fetchone()
                await connection.commit()
                return _task_from_row(claimed)
            except Exception:
                await connection.rollback()
                raise

    async def save_task(self, task: TaskRecord, worker_id: str) -> None:
        """Persist a worker result only when the worker still owns the lease."""

        sql = """
            UPDATE ingestion_tasks
            SET status = %s, retry_count = %s, result = %s, error = %s,
                worker_id = NULL, lease_expires_at = NULL, updated_at = %s
            WHERE task_id = %s AND worker_id = %s
        """
        await self._execute(sql, (
            task.status, task.retry_count,
            json.dumps(task.result, ensure_ascii=False) if task.result else None,
            json.dumps(task.error, ensure_ascii=False) if task.error else None,
            task.updated_at, task.task_id, worker_id,
        ))

    async def get_task(self, task_id: str) -> TaskRecord | None:
        row = await self._execute_for_result(
            "SELECT * FROM ingestion_tasks WHERE task_id = %s", (task_id,),
        )
        return _task_from_row(row) if row else None

    async def recover_expired_tasks(self) -> list[TaskRecord]:
        """Return abandoned running tasks to the queue after their lease expires."""

        now = datetime.now(UTC)
        update_sql = """
            UPDATE ingestion_tasks
            SET status = 'queued', recovered_after_restart = 1,
                worker_id = NULL, lease_expires_at = NULL, updated_at = %s
            WHERE status = 'running' AND lease_expires_at < %s
              AND attempts < max_attempts
        """
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(update_sql, (now, now))
                await cursor.execute("SELECT * FROM ingestion_tasks WHERE status = 'queued'")
                rows = await cursor.fetchall()
            await connection.commit()
        return [_task_from_row(row) for row in rows]

    async def create_session(self, session_id: str, title: str) -> dict[str, Any]:
        """Create a conversation container before storing any messages."""

        now = datetime.now(UTC)
        sql = """
            INSERT INTO agent_sessions (session_id, title, created_at, updated_at)
            VALUES (%s, %s, %s, %s)
        """
        await self._execute(sql, (session_id, title, now, now))
        return {
            "session_id": session_id,
            "title": title,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = await self._execute_for_result(
            "SELECT * FROM agent_sessions WHERE session_id = %s", (session_id,),
        )
        if not row:
            return None
        for key in ("created_at", "updated_at"):
            row[key] = _as_utc(row[key]).isoformat()
        return row

    async def add_message(self, message: MessageRecord) -> None:
        insert_sql = """
            INSERT INTO agent_messages
                (message_id, session_id, role, content, tool_name,
                 tool_call_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        update_sql = "UPDATE agent_sessions SET updated_at = %s WHERE session_id = %s"
        async with self.pool.acquire() as connection:
            try:
                await connection.begin()
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        insert_sql,
                        (
                            message.message_id, message.session_id, message.role,
                            message.content, message.tool_name, message.tool_call_id,
                            message.created_at,
                        ),
                    )
                    await cursor.execute(update_sql, (message.created_at, message.session_id))
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

    async def list_messages(self, session_id: str, limit: int) -> list[MessageRecord]:
        """Read recent messages in chronological order for context construction."""

        sql = """
            SELECT * FROM (
                SELECT * FROM agent_messages
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ) AS recent
            ORDER BY created_at ASC
        """
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, (session_id, limit))
                rows = await cursor.fetchall()
        return [
            MessageRecord(
                message_id=row["message_id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                tool_name=row["tool_name"],
                tool_call_id=row["tool_call_id"],
                created_at=_as_utc(row["created_at"]),
            )
            for row in rows
        ]

    async def create_agent_run(self, run: AgentRunRecord) -> None:
        sql = """
            INSERT INTO agent_runs
                (run_id, session_id, status, step_count, answer, error,
                 metadata, started_at, finished_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        await self._execute(sql, (
            run.run_id, run.session_id, run.status, run.step_count,
            run.answer, json.dumps(run.error) if run.error else None,
            json.dumps(run.metadata, ensure_ascii=False),
            run.started_at, run.finished_at,
        ))

    async def save_agent_run(self, run: AgentRunRecord) -> None:
        sql = """
            UPDATE agent_runs
            SET status = %s, step_count = %s, answer = %s, error = %s,
                metadata = %s, finished_at = %s
            WHERE run_id = %s
        """
        await self._execute(sql, (
            run.status, run.step_count, run.answer,
            json.dumps(run.error) if run.error else None,
            json.dumps(run.metadata, ensure_ascii=False),
            run.finished_at, run.run_id,
        ))

    async def save_tool_call(self, call: ToolCallRecord) -> None:
        sql = """
            INSERT INTO agent_tool_calls
                (call_id, run_id, tool_name, arguments, status, result,
                 error, duration_ms, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        await self._execute(sql, (
            call.call_id, call.run_id, call.tool_name,
            json.dumps(call.arguments, ensure_ascii=False), call.status,
            json.dumps(call.result, ensure_ascii=False) if call.result else None,
            json.dumps(call.error, ensure_ascii=False) if call.error else None,
            call.duration_ms, call.created_at,
        ))
