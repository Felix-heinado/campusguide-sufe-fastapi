"""A deterministic, evidence-grounded Agent workflow.

The project deliberately avoids pretending that a language model is always
required. Its four stages are visible in the response trace:
understand -> retrieve -> validate -> respond.
"""

from __future__ import annotations

from html import escape
from typing import Any

from .knowledge_base import load_knowledge_base, public_document
from .models import ChatRequest
from .question_policy import assess_question
from .retrieval import search_documents

MIN_SUPPORTED_SCORE = 4.0


def _limited_answer(results: list[dict[str, Any]]) -> str:
    items = "".join(
        "<li>"
        f"<strong>{escape(str(item.get('title') or '未命名资料'))}</strong>"
        f"：{escape(str(item.get('excerpt') or '暂无摘要'))}"
        "</li>"
        for item in results
    )
    return (
        "<p><strong>结论：</strong>当前资料库已找到与问题高度相关的官方资料，下面列出可直接核验的依据。</p>"
        f"<ul>{items}</ul>"
        "<p><strong>限制/下一步：</strong>请结合资料日期和适用范围使用；如涉及资格认定或办理结果，仍以学校或学院最新正式通知为准。</p>"
    )


def _policy_answer(message: str) -> dict[str, Any]:
    """Return a consistent, safe response when a question is out of scope."""

    return {
        "status": "policy_blocked",
        "answer": {
            "html": f"<p><strong>暂不能回答：</strong>{escape(message)}</p>",
            "sources": [],
            "confidence": "低：问题超出安全或知识范围",
            "engine": "question-policy",
        },
        "citations": [],
        "retrieval": [],
        "context": {},
        "trace": [
            {"stage": "understand", "outcome": "question_validated"},
            {"stage": "validate", "outcome": "policy_blocked"},
            {"stage": "respond", "outcome": "safe_refusal"},
        ],
    }


def run_agent(request: ChatRequest) -> dict[str, Any]:
    """Answer only when retrieval provides sufficiently strong evidence."""

    policy = assess_question(request.question)
    # Unsafe/private/predictive requests get a distinct policy response. A
    # normal out-of-scope campus question keeps the public insufficient-
    # evidence contract so clients can present the same guided next step.
    if not policy.allowed and policy.code != "OUT_OF_SCOPE":
        return _policy_answer(policy.message or "该问题暂不支持。")

    results = search_documents(request.question, request.context, limit=8)
    # A short but specific query may contain only one domain term (for example
    # "重修"). A score of 4 means that term matched a title/category/keyword,
    # which is strong enough to present the official excerpt with a caution.
    supported = [result for result in results if result["score"] >= MIN_SUPPORTED_SCORE]
    context = request.context.model_dump()
    context["complete"] = bool(context["college"] and context["level"] and context["year"])

    if not supported:
        return {
            "status": "insufficient_evidence",
            "answer": {
                "html": (
                    "<p><strong>结论：</strong>当前知识库没有找到足够依据，暂不生成具体规则。</p>"
                    "<p><strong>限制/下一步：</strong>可补充学院、培养层次、目标年份或更具体的事项；最终以主管部门最新通知为准。</p>"
                ),
                "sources": [],
                "confidence": "低：没有达到证据阈值",
                "engine": "lexical-rag-agent",
            },
            "citations": [],
            "retrieval": results,
            "context": context,
            "trace": [
                {"stage": "understand", "outcome": "question_validated"},
                {"stage": "retrieve", "outcome": f"{len(results)} candidates"},
                {"stage": "validate", "outcome": "evidence_below_threshold"},
                {"stage": "respond", "outcome": "refused"},
            ],
        }

    chosen = supported[:4]
    source_ids = list(dict.fromkeys(item["id"] for item in chosen))
    base = load_knowledge_base()
    citations = [public_document(base.documents_by_id[source_id]) for source_id in source_ids]
    current_count = sum(item.get("statusTone") == "current" for item in citations)
    confidence = "高：多份现行资料相互印证" if current_count >= 2 else "中：基于可追溯资料"
    return {
        "status": "grounded",
        "answer": {
            "html": _limited_answer(chosen),
            "sources": source_ids,
            "confidence": confidence,
            "engine": "lexical-rag-agent",
        },
        "citations": citations,
        "retrieval": results,
        "context": context,
        "trace": [
            {"stage": "understand", "outcome": "question_validated"},
            {"stage": "retrieve", "outcome": f"{len(results)} candidates"},
            {"stage": "validate", "outcome": "citations_verified"},
            {"stage": "respond", "outcome": "grounded"},
        ],
    }
