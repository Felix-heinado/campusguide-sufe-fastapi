"""Small model adapters used by the Agent runtime.

Both adapters return ``ModelDecision``. The runtime therefore does not care
whether the decision came from deterministic rules or a remote LLM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import Settings
from .prompts import get_system_prompt
from .question_policy import assess_question


@dataclass(slots=True)
class ToolRequest:
    name: str
    arguments: dict[str, Any]
    provider_call_id: str | None = None


@dataclass(slots=True)
class ModelDecision:
    """The model either asks for tools or returns a final answer."""

    answer: str | None = None
    tool_requests: list[ToolRequest] = field(default_factory=list)


class ModelProvider(Protocol):
    async def decide(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelDecision: ...


class DeterministicModel:
    """Offline decision maker that follows the real tool-calling loop.

    It is deliberately simple, not presented as an LLM. Its purpose is to let
    students and CI reproduce every Agent state transition without API costs.
    """

    async def decide(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelDecision:
        del tools  # The catalog is used by remote models; rules know one safe tool.
        latest = messages[-1]
        if latest["role"] == "user":
            return ModelDecision(
                tool_requests=[
                    ToolRequest(
                        name="search_documents",
                        arguments={"query": latest["content"], "limit": 5},
                    )
                ]
            )

        if latest["role"] == "tool":
            original_question = next(
                (
                    message["content"]
                    for message in reversed(messages)
                    if message["role"] == "user"
                ),
                "",
            )
            policy = assess_question(original_question)
            if not policy.allowed:
                return ModelDecision(answer=policy.message)
            payload = latest.get("parsed_content", {})
            results = payload.get("results", [])
            supported = [item for item in results if self._has_strong_evidence(item)]
            if not supported:
                return ModelDecision(answer="当前知识库没有找到足够依据，暂不生成具体结论。")
            lines = [
                f"- {item['title']}：{item.get('excerpt', '')}"
                for item in supported[:4]
            ]
            return ModelDecision(
                answer="根据检索到的资料：\n" + "\n".join(lines)
                + "\n请结合资料日期和适用范围，以最新正式通知为准。"
            )

        return ModelDecision(answer="当前执行状态无法继续，请重新提问。")

    @staticmethod
    def _has_strong_evidence(item: dict[str, Any]) -> bool:
        """Use stable component thresholds instead of comparing score scales."""

        breakdown = item.get("scoreBreakdown", {})
        return (
            (
                float(breakdown.get("lexical", 0)) >= 4
                and float(breakdown.get("queryCoverage", 1)) >= 0.30
            )
            or float(breakdown.get("semantic", 0)) >= 0.72
        )


class OpenAICompatibleModel:
    """Call an OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(self, settings: Settings) -> None:
        if not settings.agent_model_api_key or not settings.agent_model_name:
            raise ValueError("AGENT_MODEL_API_KEY and AGENT_MODEL_NAME are required")
        self.settings = settings
        self.system_prompt = get_system_prompt(settings.agent_prompt_version)

    async def decide(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelDecision:
        allowed_fields = {"role", "content", "name", "tool_calls", "tool_call_id"}
        request_messages = [{"role": "system", "content": self.system_prompt}]
        request_messages.extend(
            {key: value for key, value in message.items() if key in allowed_fields}
            for message in messages
        )
        body = {
            "model": self.settings.agent_model_name,
            "messages": request_messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self.settings.agent_model_api_key}"}
        timeout = self.settings.agent_model_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.settings.agent_model_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        tool_requests = [
            ToolRequest(
                name=item["function"]["name"],
                arguments=json.loads(item["function"].get("arguments") or "{}"),
                provider_call_id=item.get("id"),
            )
            for item in message.get("tool_calls", [])
        ]
        return ModelDecision(answer=message.get("content"), tool_requests=tool_requests)


def create_model_provider(settings: Settings) -> ModelProvider:
    if settings.agent_model_provider == "openai_compatible":
        return OpenAICompatibleModel(settings)
    return DeterministicModel()
