"""Transparent lexical retrieval for the campus knowledge base.

The scorer intentionally uses plain Python. A student can print every score,
change one weight, and immediately understand why ranking changed.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from .config import Settings
from .embeddings import cosine_similarity, create_embeddings, load_vector_index
from .knowledge_base import load_knowledge_base
from .models import UserContext

STOP_WORDS = {
    "怎么办", "怎么", "哪里", "去哪", "如何", "可以", "是否", "什么",
    "一下", "相关", "咨询", "问题", "申请", "学校", "学生", "规定",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def tokenize(query: str) -> list[str]:
    """Keep domain nouns and down-weight generic intent words.

    Chinese has no spaces, so the function keeps the full sequence and also
    creates 2-4 character n-grams. This makes short queries such as "挂科重修"
    work without a heavy tokenizer dependency.
    """

    text = normalize(query)
    terms = set(re.findall(r"[a-z0-9]+", text))
    for sequence in re.findall(r"[\u3400-\u9fff]{2,}", text):
        terms.add(sequence)
        for size in (2, 3, 4):
            terms.update(sequence[index:index + size] for index in range(len(sequence) - size + 1))
    return sorted(term for term in terms if len(term) > 1 and term not in STOP_WORDS)


def _document_text(document: dict[str, Any]) -> tuple[str, str]:
    important = normalize(" ".join((
        document.get("title", ""), document.get("category", ""),
        document.get("keywords", ""), document.get("issuer", ""),
    )))
    body = normalize(" ".join((
        document.get("excerpt", ""), document.get("applies", ""),
        document.get("note", ""),
    )))
    return important, body


def _context_bonus(document: dict[str, Any], context: UserContext) -> float:
    bonus = 0.0
    if context.category and normalize(context.category) in normalize(document.get("category", "")):
        bonus += 5
    if context.year and normalize(context.year) in normalize(document.get("date", "")):
        bonus += 2
    if context.level and normalize(context.level) in normalize(document.get("applies", "")):
        bonus += 2
    if context.college and normalize(context.college) in normalize(document.get("applies", "")):
        bonus += 1
    return bonus


def search_documents(
    query: str, context: UserContext | None = None, limit: int = 5
) -> list[dict[str, Any]]:
    """Rank documents and expose a score breakdown for debugging."""

    context = context or UserContext()
    terms = tokenize(query)
    results: list[dict[str, Any]] = []
    for document in load_knowledge_base().documents:
        important, body = _document_text(document)
        title_matches = [term for term in terms if term in important]
        body_matches = [term for term in terms if term in body and term not in title_matches]
        lexical = len(title_matches) * 4 + len(body_matches) * 1.5
        metadata = _context_bonus(document, context)
        score = lexical + metadata
        if score <= 0:
            continue
        results.append({
            "id": document["id"], "title": document.get("title"),
            "category": document.get("category"), "issuer": document.get("issuer"),
            "date": document.get("date"), "status": document.get("status"),
            "score": round(score, 3),
            "scoreBreakdown": {"lexical": lexical, "metadata": metadata, "semantic": 0},
            "matchedBy": ["domain_term"] if title_matches else ["body_term"],
            "matchedTokens": title_matches + body_matches,
            "excerpt": document.get("excerpt", ""),
        })
    results.sort(key=lambda item: (-item["score"], str(item.get("date", ""))), reverse=False)
    return results[:limit]


def get_evidence(chunk_id: str) -> dict[str, Any] | None:
    """Return one traceable evidence chunk by its stable ID."""

    return load_knowledge_base().chunks_by_id.get(chunk_id)


async def hybrid_search_documents(
    query: str,
    context: UserContext,
    limit: int,
    settings: Settings,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Blend lexical and semantic scores, or safely fall back to lexical search."""

    lexical = search_documents(query, context, max(limit, 20))
    if not settings.rag_enable_semantic_search:
        return lexical[:limit], {"mode": "lexical", "fallback": None}

    index = load_vector_index(settings.embedding_index_path)
    if not index:
        return lexical[:limit], {"mode": "lexical", "fallback": "index_missing"}

    try:
        query_vector = (await create_embeddings([query], settings))[0]
    except (httpx.HTTPError, ValueError) as error:
        return lexical[:limit], {
            "mode": "lexical",
            "fallback": "embedding_unavailable",
            "reason": type(error).__name__,
        }

    semantic_scores = {
        row["documentId"]: cosine_similarity(query_vector, row["values"])
        for row in index["vectors"]
    }
    by_id = {item["id"]: item for item in lexical}
    for document in load_knowledge_base().documents:
        document_id = document["id"]
        semantic = max(semantic_scores.get(document_id, 0.0), 0.0)
        if semantic <= 0 and document_id not in by_id:
            continue
        item = by_id.setdefault(
            document_id,
            {
                "id": document_id,
                "title": document.get("title"),
                "category": document.get("category"),
                "issuer": document.get("issuer"),
                "date": document.get("date"),
                "status": document.get("status"),
                "score": 0.0,
                "scoreBreakdown": {"lexical": 0, "metadata": 0, "semantic": 0},
                "matchedBy": [],
                "matchedTokens": [],
                "excerpt": document.get("excerpt", ""),
            },
        )
        lexical_normalized = min(item["scoreBreakdown"]["lexical"] / 20, 1)
        metadata_normalized = min(item["scoreBreakdown"]["metadata"] / 10, 1)
        item["scoreBreakdown"]["semantic"] = round(semantic, 4)
        item["score"] = round(
            lexical_normalized * 0.55 + semantic * 0.35 + metadata_normalized * 0.10,
            4,
        )
        if semantic > 0:
            item["matchedBy"] = list(
                dict.fromkeys([*item["matchedBy"], "semantic_vector"])
            )

    results = sorted(by_id.values(), key=lambda item: item["score"], reverse=True)
    return results[:limit], {"mode": "hybrid", "fallback": None}
