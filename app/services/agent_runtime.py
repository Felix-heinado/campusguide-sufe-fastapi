"""Tool-calling Agent runtime with sessions, limits, timeouts, and audit logs."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..config import Settings
from ..model_provider import ModelProvider
from ..models import AgentRunRequest
from ..repositories.base import (
    AgentRunRecord,
    MessageRecord,
    Repository,
    ToolCallRecord,
)
from ..tools import TOOL_SCHEMAS, ToolError, call_tool


class AgentRuntime:
    """Coordinate model decisions, tool execution, and persistent state."""

    def __init__(
        self,
        repository: Repository,
        model: ModelProvider,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.model = model
        self.settings = settings

    async def run(self, request: AgentRunRequest) -> dict[str, Any]:
        """Collect streaming events and return a normal JSON response."""

        events = [event async for event in self.stream(request)]
        final = next(event for event in reversed(events) if event["event"] == "done")
        return final["data"]

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[dict[str, Any]]:
        """Yield observable Agent events while executing the bounded loop."""

        session = await self._get_or_create_session(request)
        yield {"event": "session", "data": session}

        user_message = MessageRecord(
            message_id=str(uuid4()), session_id=session["session_id"],
            role="user", content=request.question,
        )
        await self.repository.add_message(user_message)

        run = AgentRunRecord(run_id=str(uuid4()), session_id=session["session_id"])
        await self.repository.create_agent_run(run)
        yield {"event": "run_started", "data": run.to_dict()}

        history = await self.repository.list_messages(
            session["session_id"], self.settings.agent_history_limit
        )
        # Historical tool protocol messages are not replayed into a new run.
        # Keeping recent user/assistant turns gives conversational context while
        # each new run builds a fresh, valid tool-call sequence.
        messages = [
            {"role": message.role, "content": message.content, "name": message.tool_name}
            for message in history
            if message.role in {"user", "assistant"}
        ]

        try:
            for step in range(1, self.settings.agent_max_steps + 1):
                run.step_count = step
                decision = await asyncio.wait_for(
                    self.model.decide(messages, TOOL_SCHEMAS),
                    timeout=self.settings.agent_model_timeout_seconds,
                )
                if decision.answer is not None and not decision.tool_requests:
                    async for event in self._finish(run, decision.answer, messages):
                        yield event
                    return

                if not decision.tool_requests:
                    raise RuntimeError("model returned neither an answer nor a tool request")

                assistant_tool_calls = []
                for tool_request in decision.tool_requests:
                    provider_call_id = tool_request.provider_call_id or str(uuid4())
                    assistant_tool_calls.append({
                        "id": provider_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_request.name,
                            "arguments": json.dumps(tool_request.arguments, ensure_ascii=False),
                        },
                    })
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": assistant_tool_calls,
                })

                for tool_request, protocol_call in zip(
                    decision.tool_requests, assistant_tool_calls, strict=True
                ):
                    call_id = str(uuid4())
                    yield {
                        "event": "tool_started",
                        "data": {"callId": call_id, "name": tool_request.name, "step": step},
                    }
                    result, call_record = await self._execute_tool(
                        run.run_id, call_id, tool_request.name, tool_request.arguments
                    )
                    await self.repository.save_tool_call(call_record)
                    yield {"event": "tool_finished", "data": self._public_tool_call(call_record)}

                    tool_content = json.dumps(result, ensure_ascii=False)
                    tool_message = MessageRecord(
                        message_id=str(uuid4()), session_id=session["session_id"],
                        role="tool", content=tool_content,
                        tool_name=tool_request.name, tool_call_id=call_id,
                    )
                    await self.repository.add_message(tool_message)
                    messages.append({
                        "role": "tool", "content": tool_content,
                        "name": tool_request.name, "parsed_content": result,
                        "tool_call_id": protocol_call["id"],
                    })

            run.status = "max_steps"
            run.error = {"code": "MAX_STEPS", "message": "Agent reached its step limit"}
            run.finished_at = datetime.now(UTC)
            await self.repository.save_agent_run(run)
            yield {"event": "error", "data": run.error}
            yield {"event": "done", "data": {"run": run.to_dict(), "answer": None}}
        except Exception as error:
            run.status = "failed"
            run.error = {"code": type(error).__name__, "message": str(error)}
            run.finished_at = datetime.now(UTC)
            await self.repository.save_agent_run(run)
            yield {"event": "error", "data": run.error}
            yield {"event": "done", "data": {"run": run.to_dict(), "answer": None}}

    async def _get_or_create_session(self, request: AgentRunRequest) -> dict[str, Any]:
        if request.session_id:
            existing = await self.repository.get_session(request.session_id)
            if not existing:
                raise ValueError("session not found")
            return existing
        title = request.question[:40]
        return await self.repository.create_session(str(uuid4()), title)

    async def _execute_tool(
        self,
        run_id: str,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], ToolCallRecord]:
        started = time.perf_counter()
        record = ToolCallRecord(
            call_id=call_id, run_id=run_id, tool_name=name,
            arguments=arguments, status="running",
        )
        try:
            result = await asyncio.wait_for(
                call_tool(name, arguments, self.repository, self.settings),
                timeout=self.settings.agent_tool_timeout_seconds,
            )
            record.status = "succeeded"
            record.result = result
            return result, record
        except TimeoutError:
            record.status = "timed_out"
            record.error = {"code": "TOOL_TIMEOUT", "message": f"{name} timed out"}
            return {"error": record.error}, record
        except ToolError as error:
            record.status = "failed"
            record.error = {"code": error.code, "message": str(error)}
            return {"error": record.error}, record
        finally:
            record.duration_ms = round((time.perf_counter() - started) * 1000, 3)

    async def _finish(
        self,
        run: AgentRunRecord,
        answer: str,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        del messages  # Reserved for later token/context metrics.
        assistant = MessageRecord(
            message_id=str(uuid4()), session_id=run.session_id,
            role="assistant", content=answer,
        )
        await self.repository.add_message(assistant)
        run.status = "succeeded"
        run.answer = answer
        run.finished_at = datetime.now(UTC)
        await self.repository.save_agent_run(run)
        yield {"event": "answer", "data": {"content": answer}}
        yield {
            "event": "done",
            "data": {"run": run.to_dict(), "answer": answer, "sessionId": run.session_id},
        }

    @staticmethod
    def _public_tool_call(call: ToolCallRecord) -> dict[str, Any]:
        return {
            "callId": call.call_id, "name": call.tool_name,
            "status": call.status, "durationMs": call.duration_ms,
            "result": call.result, "error": call.error,
        }


def encode_sse(event: dict[str, Any]) -> str:
    """Encode one event using the simple Server-Sent Events text format."""

    return f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
