"""A deterministic, evidence-grounded Agent workflow.

The project deliberately avoids pretending that a language model is always
required. Its four stages are visible in the response trace:
understand -> retrieve -> validate -> respond.
"""

from __future__ import annotations

from typing import Any

from .knowledge_base import load_knowledge_base, public_document
from .models import ChatRequest
from .retrieval import search_documents

MIN_SUPPORTED_SCORE = 4.0


def _limited_answer(results: list[dict[str, Any]]) -> str:
    items = "".join(
        f"<li><strong>{item['title']}</strong>：{item['excerpt']}</li>" for item in results
    )
    return (
        "<p><strong>根据当前知识库，找到以下相关资料：</strong></p>"
        f"<ul>{items}</ul>"
        "<p>请结合资料日期和适用范围，以学校或学院最新通知为准。</p>"
    )


def run_agent(request: ChatRequest) -> dict[str, Any]:
    """Answer only when retrieval provides sufficiently strong evidence."""

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
                "html": "<p>当前知识库没有找到足够依据，暂不生成具体结论。</p>",
                "sources": [],
                "confidence": "低",
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
    return {
        "status": "grounded",
        "answer": {
            "html": _limited_answer(chosen),
            "sources": source_ids,
            "confidence": "中：基于可追溯资料",
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
