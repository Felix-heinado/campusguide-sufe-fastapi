"""A small asynchronous task queue with idempotency, leases, and retries.

This module models the same concerns as a larger queue system while remaining
small enough to understand in one sitting. In a production deployment,
``asyncio.Queue`` can be replaced by Redis Streams, RabbitMQ, or Kafka without
changing the HTTP API or task state machine.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from uuid import uuid4

from ..knowledge_base import load_knowledge_base
from ..models import IngestionTaskRequest
from ..repositories.base import Repository, TaskRecord

logger = logging.getLogger(__name__)


class TaskService:
    """Own the queue, worker lifecycle, and task state transitions."""

    def __init__(
        self,
        repository: Repository,
        worker_count: int = 2,
        lease_seconds: int = 30,
    ) -> None:
        self.repository = repository
        self.worker_count = max(worker_count, 1)
        self.lease_seconds = max(lease_seconds, 5)
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.workers: list[asyncio.Task] = []
        self.closing = False

    async def start(self) -> None:
        """Recover abandoned tasks before accepting new work."""

        self.closing = False
        for task in await self.repository.recover_expired_tasks():
            await self.queue.put(task.task_id)
        self.workers = [
            asyncio.create_task(self._worker(index), name=f"ingestion-worker-{index}")
            for index in range(self.worker_count)
        ]

    async def close(self) -> None:
        """Stop accepting work and let workers exit without losing queue state."""

        self.closing = True
        for _ in self.workers:
            await self.queue.put(None)
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

    async def create_task(self, request: IngestionTaskRequest) -> TaskRecord:
        if self.closing:
            raise RuntimeError("service is shutting down")

        now = datetime.now(UTC)
        candidate = TaskRecord(
            task_id=str(uuid4()),
            source=request.source.strip(),
            idempotency_key=request.idempotency_key.strip() if request.idempotency_key else None,
            kind=(
                "official-manifest-registration"
                if request.source == "official-regulations-package"
                else "source-registration"
            ),
            created_at=now,
            updated_at=now,
        )
        task, created = await self.repository.create_or_get_task(candidate)
        if created or task.status == "queued":
            await self.queue.put(task.task_id)
        return task

    async def get_task(self, task_id: str) -> TaskRecord | None:
        return await self.repository.get_task(task_id)

    async def _worker(self, index: int) -> None:
        """Continuously claim task IDs; the repository decides the real owner."""

        worker_id = f"{os.getpid()}:{index}:{uuid4()}"
        while True:
            task_id = await self.queue.get()
            try:
                if task_id is None:
                    return
                await self._execute(task_id, worker_id)
            except Exception:
                logger.exception("task execution failed", extra={"task_id": task_id})
            finally:
                self.queue.task_done()

    async def _execute(self, task_id: str, worker_id: str) -> None:
        """Claim, execute, and persist one state transition."""

        task = await self.repository.claim_task(task_id, worker_id, self.lease_seconds)
        if task is None:
            return  # Another worker already owns or completed this task.

        try:
            task.result = await self._perform_ingestion(task)
            task.status = "succeeded"
            task.error = None
        except Exception as error:  # The retry path is intentionally explicit.
            task.error = {"code": "INGESTION_FAILED", "message": str(error)}
            if task.attempts < task.max_attempts:
                task.retry_count += 1
                task.status = "queued"
            else:
                task.status = "failed"
        task.updated_at = datetime.now(UTC)
        await self.repository.save_task(task, worker_id)
        if task.status == "queued" and not self.closing:
            await self.queue.put(task.task_id)

    @staticmethod
    async def _perform_ingestion(task: TaskRecord) -> dict:
        """Represent a short I/O-bound registration step without blocking HTTP."""

        await asyncio.sleep(0)  # Yield to other requests and worker tasks.
        base = load_knowledge_base()
        if task.source == "force-failure-for-test":
            raise RuntimeError("simulated ingestion failure")
        return {
            "registeredDocuments": len(base.documents),
            "evidenceChunks": len(base.evidence_chunks),
            "nextStage": "hybrid-retrieval",
            "note": "公开资料快照已登记，可由检索服务读取。",
        }

