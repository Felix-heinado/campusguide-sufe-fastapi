import json

import httpx
import pytest

from app.config import Settings
from app.model_provider import OpenAICompatibleModel
from app.prompts import PROMPTS, get_system_prompt


def test_prompt_versions_encode_progressively_stricter_rules():
    assert set(PROMPTS) == {"v1", "v2", "v3"}
    assert "必须先调用" in PROMPTS["v2"]
    assert "历史通知" in PROMPTS["v3"]
    assert "结论—依据—限制/下一步" in PROMPTS["v3"]


def test_unknown_prompt_version_fails_fast():
    with pytest.raises(ValueError, match="unknown prompt version"):
        get_system_prompt("v99")


@pytest.mark.asyncio
async def test_remote_model_sends_selected_prompt_and_tool_protocol(monkeypatch):
    captured = {}

    async def fake_post(self, url, headers, json):
        del self
        captured.update({"url": url, "headers": headers, "body": json})
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [{
                    "message": {
                        "content": None,
                        "tool_calls": [{
                            "id": "provider-call-1",
                            "type": "function",
                            "function": {
                                "name": "search_documents",
                                "arguments": json_module.dumps({"query": "挂科重修"}),
                            },
                        }],
                    }
                }]
            },
        )

    json_module = json
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    settings = Settings(
        agent_model_api_key="test-only", agent_model_name="mock-tool-model",
        agent_prompt_version="v3",
    )
    model = OpenAICompatibleModel(settings)

    decision = await model.decide(
        [{"role": "user", "content": "挂科重修"}],
        [{"type": "function", "function": {"name": "search_documents"}}],
    )

    assert captured["body"]["messages"][0] == {
        "role": "system", "content": PROMPTS["v3"]
    }
    assert decision.tool_requests[0].name == "search_documents"
    assert decision.tool_requests[0].provider_call_id == "provider-call-1"
