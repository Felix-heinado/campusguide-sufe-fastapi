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

