import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.repositories.base import TaskRecord


@pytest.mark.asyncio
async def test_json_feedback_writes_are_serialized(repository):
    async def write(index: int):
        await repository.insert_feedback({
            "feedback_id": str(uuid4()), "question_hash": str(index),
            "helpful": True, "reasons": [], "created_at": datetime.now(UTC),
        })

    await asyncio.gather(*(write(index) for index in range(50)))
    rows = json.loads(repository.feedback_path.read_text(encoding="utf-8"))
    assert len(rows) == 50


@pytest.mark.asyncio
async def test_expired_worker_lease_returns_task_to_queue(repository):
    task = TaskRecord(
        task_id=str(uuid4()), source="test", idempotency_key="lease-test", kind="test"
    )
    stored, _ = await repository.create_or_get_task(task)
    claimed = await repository.claim_task(stored.task_id, "dead-worker", 5)
    assert claimed is not None

    # Simulate a crashed worker whose lease expired in the past.
    rows = json.loads(repository.task_path.read_text(encoding="utf-8"))
    rows[0]["lease_expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    repository.task_path.write_text(json.dumps(rows), encoding="utf-8")

    recovered = await repository.recover_expired_tasks()
    assert recovered[0].status == "queued"
    assert recovered[0].recovered_after_restart is True

