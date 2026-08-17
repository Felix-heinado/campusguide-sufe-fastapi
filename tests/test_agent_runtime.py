
import pytest

from app.config import Settings
from app.model_provider import ModelDecision, ToolRequest
from app.models import AgentRunRequest
from app.services.agent_runtime import AgentRuntime


@pytest.mark.asyncio
async def test_agent_runs_a_real_tool_loop_and_persists_messages(repository):
    await repository.start()
    runtime = AgentRuntime(repository, _SearchThenAnswerModel(), Settings())

    result = await runtime.run(AgentRunRequest(question="挂科重修怎么办"))

    assert result["run"]["status"] == "succeeded"
    assert result["run"]["step_count"] == 2
    assert "学籍管理" in result["answer"]
    messages = await repository.list_messages(result["sessionId"], 20)
    assert [message.role for message in messages] == ["user", "tool", "assistant"]


@pytest.mark.asyncio
async def test_agent_can_continue_an_existing_session(repository):
    await repository.start()
    runtime = AgentRuntime(repository, _SearchThenAnswerModel(), Settings())
    first = await runtime.run(AgentRunRequest(question="挂科重修怎么办"))
    second = await runtime.run(AgentRunRequest(
        question="再说明一下资料时间",
        session_id=first["sessionId"],
    ))

    assert second["sessionId"] == first["sessionId"]
    messages = await repository.list_messages(first["sessionId"], 20)
    assert len(messages) == 6


@pytest.mark.asyncio
async def test_max_steps_stops_a_model_that_never_finishes(repository):
    await repository.start()
    settings = Settings(agent_max_steps=2)
    runtime = AgentRuntime(repository, _LoopingModel(), settings)

    result = await runtime.run(AgentRunRequest(question="测试循环"))

    assert result["run"]["status"] == "max_steps"
    assert result["run"]["step_count"] == 2
    assert result["answer"] is None


def test_sse_endpoint_exposes_execution_order(client):
    with client.stream(
        "POST",
        "/api/agent/stream",
        json={"question": "挂科重修怎么办"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    events = [
        line.removeprefix("event: ")
        for line in body.splitlines()
        if line.startswith("event:")
    ]
    assert events == [
        "session", "run_started", "tool_started", "tool_finished", "answer", "done"
    ]


class _SearchThenAnswerModel:
    """Test double that proves the runtime, not model intelligence, is tested."""

    async def decide(self, messages, tools):
        del tools
        if messages[-1]["role"] == "user":
            return ModelDecision(tool_requests=[
                ToolRequest("search_documents", {"query": messages[-1]["content"], "limit": 3})
            ])
        result = messages[-1]["parsed_content"]
        return ModelDecision(answer=result["results"][0]["title"])


class _LoopingModel:
    async def decide(self, messages, tools):
        del messages, tools
        return ModelDecision(tool_requests=[
            ToolRequest("search_documents", {"query": "挂科重修", "limit": 1})
        ])
