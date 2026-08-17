"""Optional integration checks against a real local MySQL instance.

Run with ``RUN_MYSQL_TESTS=1`` after executing ``docs/schema.mysql.sql``.
The normal test suite skips this file so CI does not require private secrets.
"""

import os
from uuid import uuid4

import pytest

from app.config import Settings
from app.model_provider import DeterministicModel
from app.models import AgentRunRequest
from app.repositories.base import TaskRecord
from app.repositories.mysql import MySQLRepository
from app.services.agent_runtime import AgentRuntime

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_MYSQL_TESTS") != "1",
    reason="set RUN_MYSQL_TESTS=1 to run real MySQL integration tests",
)


@pytest.mark.asyncio
async def test_mysql_idempotency_and_task_claim_are_atomic():
    repository = MySQLRepository(Settings(persistence_backend="mysql"))
    await repository.start()
    try:
        key = f"integration-{uuid4()}"
        first = TaskRecord(
            task_id=str(uuid4()), source="integration", idempotency_key=key, kind="test"
        )
        second = TaskRecord(
            task_id=str(uuid4()), source="integration", idempotency_key=key, kind="test"
        )
        stored_first, created_first = await repository.create_or_get_task(first)
        stored_second, created_second = await repository.create_or_get_task(second)

        assert created_first is True
        assert created_second is False
        assert stored_first.task_id == stored_second.task_id

        claimed = await repository.claim_task(stored_first.task_id, "integration-worker", 10)
        duplicate_claim = await repository.claim_task(
            stored_first.task_id, "another-worker", 10
        )
        assert claimed is not None
        assert duplicate_claim is None
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_mysql_persists_agent_session_messages_run_and_tool_call():
    settings = Settings(persistence_backend="mysql")
    repository = MySQLRepository(settings)
    await repository.start()
    try:
        runtime = AgentRuntime(repository, DeterministicModel(), settings)
        result = await runtime.run(AgentRunRequest(question="挂科重修怎么办"))

        assert result["run"]["status"] == "succeeded"
        messages = await repository.list_messages(result["sessionId"], 20)
        assert [message.role for message in messages] == ["user", "tool", "assistant"]

        async with repository.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT COUNT(*) AS count FROM agent_tool_calls WHERE run_id = %s",
                    (result["run"]["run_id"],),
                )
                row = await cursor.fetchone()
        assert row["count"] == 1
    finally:
        await repository.close()
