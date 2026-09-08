
import asyncio

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


@pytest.mark.asyncio
async def test_unknown_tool_is_audited_and_returned_to_model(repository):
    await repository.start()
    runtime = AgentRuntime(repository, _UnknownToolThenAnswerModel(), Settings())

    result = await runtime.run(AgentRunRequest(question="测试未知工具"))

    assert result["run"]["status"] == "succeeded"
    assert result["answer"] == "UNKNOWN_TOOL"
    state = repository._read_agent_state()
    assert state["tool_calls"][0]["status"] == "failed"
    assert state["tool_calls"][0]["error"]["code"] == "UNKNOWN_TOOL"


@pytest.mark.asyncio
async def test_invalid_tool_argument_type_is_rejected(repository):
    await repository.start()
    runtime = AgentRuntime(repository, _InvalidArgumentThenAnswerModel(), Settings())

    result = await runtime.run(AgentRunRequest(question="测试参数"))

    assert result["answer"] == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_tool_timeout_is_visible_to_the_model(repository, monkeypatch):
    await repository.start()

    async def slow_tool(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.05)
        return {"late": True}

    monkeypatch.setattr("app.services.agent_runtime.call_tool", slow_tool)
    runtime = AgentRuntime(
        repository, _ErrorCodeThenAnswerModel(),
        Settings(agent_tool_timeout_seconds=0.001),
    )

    result = await runtime.run(AgentRunRequest(question="测试超时"))

    assert result["answer"] == "TOOL_TIMEOUT"


@pytest.mark.asyncio
async def test_unexpected_tool_exception_is_sanitized_and_audited(repository, monkeypatch):
    await repository.start()

    async def broken_tool(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("private database detail")

    monkeypatch.setattr("app.services.agent_runtime.call_tool", broken_tool)
    runtime = AgentRuntime(repository, _ErrorCodeThenAnswerModel(), Settings())

    result = await runtime.run(AgentRunRequest(question="测试异常"))

    assert result["answer"] == "TOOL_EXECUTION_ERROR"
    assert "private database detail" not in str(result)


@pytest.mark.asyncio
async def test_multiple_tools_in_one_decision_keep_protocol_order(repository):
    await repository.start()
    runtime = AgentRuntime(repository, _TwoToolsThenAnswerModel(), Settings())

    result = await runtime.run(AgentRunRequest(question="挂科重修"))

    assert result["run"]["status"] == "succeeded"
    state = repository._read_agent_state()
    names = [row["tool_name"] for row in state["tool_calls"]]
    assert names == ["search_documents", "get_document"]


@pytest.mark.asyncio
async def test_duplicate_feedback_side_effect_is_blocked_in_one_run(repository):
    await repository.start()
    runtime = AgentRuntime(repository, _DuplicateFeedbackModel(), Settings())

    result = await runtime.run(AgentRunRequest(question="这个回答有帮助"))

    assert result["answer"] == "DUPLICATE_SIDE_EFFECT"
    feedback_rows = repository._read(repository.feedback_path)
    assert len(feedback_rows) == 1


@pytest.mark.asyncio
async def test_model_timeout_has_stable_error_code(repository):
    await repository.start()
    runtime = AgentRuntime(
        repository, _SlowModel(), Settings(agent_model_timeout_seconds=0.001)
    )

    result = await runtime.run(AgentRunRequest(question="测试模型超时"))

    assert result["run"]["status"] == "failed"
    assert result["run"]["error"]["code"] == "MODEL_TIMEOUT"


@pytest.mark.asyncio
async def test_model_returning_nothing_fails_cleanly(repository):
    await repository.start()
    runtime = AgentRuntime(repository, _EmptyDecisionModel(), Settings())

    result = await runtime.run(AgentRunRequest(question="测试空决策"))

    assert result["run"]["status"] == "failed"
    assert result["run"]["error"]["code"] == "RuntimeError"


@pytest.mark.asyncio
async def test_long_tool_result_is_truncated_before_model_context(repository, monkeypatch):
    await repository.start()

    async def large_tool(*args, **kwargs):
        del args, kwargs
        return {"payload": "x" * 2000}

    monkeypatch.setattr("app.services.agent_runtime.call_tool", large_tool)
    model = _TruncationObserverModel()
    runtime = AgentRuntime(
        repository, model, Settings(agent_tool_result_max_chars=100)
    )

    result = await runtime.run(AgentRunRequest(question="测试大结果"))

    assert result["answer"] == "truncated"
    assert result["run"]["metadata"]["toolResultsTruncated"] == 1


@pytest.mark.asyncio
async def test_recent_conversation_context_excludes_historical_tools(repository):
    await repository.start()
    runtime = AgentRuntime(repository, _SearchThenAnswerModel(), Settings())
    first = await runtime.run(AgentRunRequest(question="第一问"))
    await runtime.run(AgentRunRequest(question="第二问", session_id=first["sessionId"]))

    observer = _HistoryObserverModel()
    runtime = AgentRuntime(
        repository, observer,
        Settings(agent_history_limit=3, agent_context_max_chars=1000),
    )
    result = await runtime.run(
        AgentRunRequest(question="第三问", session_id=first["sessionId"])
    )

    assert observer.roles == ["user", "assistant", "user"]
    context = result["run"]["metadata"]["context"]
    assert context["historicalToolMessagesReplayed"] is False
    assert context["truncated"] is True
    assert "history_limit" in context["reasons"]


@pytest.mark.asyncio
async def test_character_limit_reason_is_recorded(repository):
    await repository.start()
    runtime = AgentRuntime(repository, _ImmediateAnswerModel(), Settings())
    first = await runtime.run(AgentRunRequest(question="甲" * 40))

    runtime = AgentRuntime(
        repository, _ImmediateAnswerModel(),
        Settings(agent_history_limit=20, agent_context_max_chars=20),
    )
    result = await runtime.run(
        AgentRunRequest(question="乙" * 10, session_id=first["sessionId"])
    )

    context = result["run"]["metadata"]["context"]
    assert context["truncated"] is True
    assert "character_limit" in context["reasons"]


def test_nonexistent_session_returns_404(client):
    response = client.post(
        "/api/agent/run",
        json={"question": "继续", "session_id": "00000000-0000-0000-0000-000000000000"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SESSION_NOT_FOUND"


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


class _UnknownToolThenAnswerModel:
    async def decide(self, messages, tools):
        del tools
        if messages[-1]["role"] == "user":
            return ModelDecision(tool_requests=[ToolRequest("delete_everything", {})])
        return ModelDecision(answer=messages[-1]["parsed_content"]["error"]["code"])


class _InvalidArgumentThenAnswerModel:
    async def decide(self, messages, tools):
        del tools
        if messages[-1]["role"] == "user":
            return ModelDecision(tool_requests=[
                ToolRequest("search_documents", {"query": "挂科", "limit": "many"})
            ])
        return ModelDecision(answer=messages[-1]["parsed_content"]["error"]["code"])


class _ErrorCodeThenAnswerModel:
    async def decide(self, messages, tools):
        del tools
        if messages[-1]["role"] == "user":
            return ModelDecision(tool_requests=[
                ToolRequest("search_documents", {"query": "挂科", "limit": 1})
            ])
        return ModelDecision(answer=messages[-1]["parsed_content"]["error"]["code"])


class _TwoToolsThenAnswerModel:
    async def decide(self, messages, tools):
        del tools
        if messages[-1]["role"] == "user":
            return ModelDecision(tool_requests=[
                ToolRequest("search_documents", {"query": "挂科重修", "limit": 1}),
                ToolRequest("get_document", {"documentId": "KB-2017-001"}),
            ])
        return ModelDecision(answer="two tools completed")


class _DuplicateFeedbackModel:
    async def decide(self, messages, tools):
        del tools
        feedback = {"question": "这个回答有帮助", "helpful": True, "reasons": []}
        tool_messages = [message for message in messages if message["role"] == "tool"]
        if not tool_messages:
            return ModelDecision(tool_requests=[
                ToolRequest("record_feedback", feedback),
                ToolRequest("record_feedback", feedback),
            ])
        return ModelDecision(answer=tool_messages[-1]["parsed_content"]["error"]["code"])


class _SlowModel:
    async def decide(self, messages, tools):
        del messages, tools
        await asyncio.sleep(0.05)
        return ModelDecision(answer="late")


class _EmptyDecisionModel:
    async def decide(self, messages, tools):
        del messages, tools
        return ModelDecision()


class _TruncationObserverModel:
    async def decide(self, messages, tools):
        del tools
        if messages[-1]["role"] == "user":
            return ModelDecision(tool_requests=[
                ToolRequest("search_documents", {"query": "large", "limit": 1})
            ])
        payload = messages[-1]["parsed_content"]
        return ModelDecision(answer="truncated" if payload.get("truncated") else "full")


class _HistoryObserverModel:
    def __init__(self):
        self.roles = []

    async def decide(self, messages, tools):
        del tools
        self.roles = [message["role"] for message in messages]
        return ModelDecision(answer="observed")


class _ImmediateAnswerModel:
    async def decide(self, messages, tools):
        del messages, tools
        return ModelDecision(answer="ok")
