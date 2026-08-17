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
from .base import TaskRecord


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
            minsize=1,
            maxsize=10,
            autocommit=False,
            cursorclass=aiomysql.DictCursor,
        )

    async def close(self) -> None:
        if self.pool is not None:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None

    async def insert_feedback(self, row: dict[str, Any]) -> None:
        """Store feedback with a unique public ID and a searchable question hash."""

        sql = """
            INSERT INTO feedback
                (feedback_id, question_hash, helpful, reasons, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    sql,
                    (
                        row["feedback_id"], row["question_hash"], row["helpful"],
                        json.dumps(row["reasons"], ensure_ascii=False), row["created_at"],
                    ),
                )
            await connection.commit()

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
                affected = await cursor.execute(
                    insert_sql,
                    (
                        candidate.task_id, candidate.source, candidate.idempotency_key,
                        candidate.kind, candidate.max_attempts, candidate.created_at,
                        candidate.updated_at,
                    ),
                )
                await cursor.execute(lookup_sql, (candidate.task_id, candidate.idempotency_key))
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
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    sql,
                    (
                        task.status, task.retry_count,
                        json.dumps(task.result, ensure_ascii=False) if task.result else None,
                        json.dumps(task.error, ensure_ascii=False) if task.error else None,
                        task.updated_at, task.task_id, worker_id,
                    ),
                )
            await connection.commit()

    async def get_task(self, task_id: str) -> TaskRecord | None:
        async with self.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT * FROM ingestion_tasks WHERE task_id = %s", (task_id,))
                row = await cursor.fetchone()
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
