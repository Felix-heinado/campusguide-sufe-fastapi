"""Transparent lexical retrieval for the campus knowledge base.

The scorer intentionally uses plain Python. A student can print every score,
change one weight, and immediately understand why ranking changed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx

from .config import Settings
from .embeddings import cosine_similarity, create_embeddings, load_vector_index
from .knowledge_base import load_knowledge_base
from .models import UserContext

STOP_WORDS = {
    "怎么办", "怎么", "哪里", "去哪", "如何", "可以", "是否", "什么",
    "一下", "相关", "咨询", "问题", "申请", "学校", "学生", "规定",
    "学院", "细则", "本科生", "研究生",
}

# Normalisation ceilings used when blending lexical and semantic scores.
_LEXICAL_NORM_CEILING = 20
_METADATA_NORM_CEILING = 10
_HYBRID_WEIGHT_LEXICAL = 0.55
_HYBRID_WEIGHT_SEMANTIC = 0.35
_HYBRID_WEIGHT_METADATA = 0.10

INTENT_PHRASES = (
    "怎么办", "怎么", "如何", "哪里", "去哪", "是否", "有没有", "有什么",
    "可以", "相关", "规定", "申请", "学校", "学生", "本科生", "研究生",
    "帮我", "给我", "一下", "看什么", "看哪份", "看哪里",
    "只问", "什么时候", "能不能", "可以吗",
)

QUERY_SYNONYMS = {
    "毕业证": ("毕业证书",),
    "丢了": ("遗失",),
    "校园卡": ("一卡通",),
    "纸质就业协议": ("纸签", "就业协议书"),
    "纸签": ("就业协议",),
    "推免": ("推荐免试",),
    "gpa": ("绩点", "平均学分绩点"),
}


@dataclass(frozen=True, slots=True)
class RetrievalPreset:
    """One explainable lexical-ranking version used in offline comparisons."""

    name: str
    remove_intent_words: bool
    important_weight: float
    body_weight: float
    evidence_weight: float = 0.0
    quality_bonus: bool = False


RETRIEVAL_PRESETS = {
    "v1": RetrievalPreset("v1", False, 1.0, 1.0),
    "v2": RetrievalPreset("v2", True, 1.0, 1.0),
    "v3": RetrievalPreset("v3", True, 4.0, 1.5),
    # V4 searches parsed evidence as well as document summaries. A small
    # quality bonus breaks ties in favour of current, fully parsed sources.
    "v4": RetrievalPreset("v4", True, 4.0, 1.5, 0.75, True),
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def tokenize(query: str, remove_intent_words: bool = True) -> list[str]:
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
    for source, expansions in QUERY_SYNONYMS.items():
        if source in text:
            terms.update(expansions)
    return sorted(
        term for term in terms
        if len(term) > 1 and (not remove_intent_words or term not in STOP_WORDS)
    )


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


@lru_cache
def _evidence_text_by_document() -> dict[str, str]:
    """Group parsed evidence once so deep clauses can participate in search."""

    grouped: dict[str, list[str]] = {}
    for chunk in load_knowledge_base().evidence_chunks:
        document_id = str(chunk.get("documentId", ""))
        grouped.setdefault(document_id, []).append(str(chunk.get("content", "")))
    return {document_id: normalize(" ".join(parts)) for document_id, parts in grouped.items()}


@lru_cache
def _search_corpus_by_document() -> dict[str, str]:
    evidence = _evidence_text_by_document()
    return {
        document["id"]: " ".join((*_document_text(document), evidence.get(document["id"], "")))
        for document in load_knowledge_base().documents
    }


@lru_cache
def _inverse_document_frequency(term: str) -> float:
    """Give specific campus terms more influence than common form words."""

    corpus = _search_corpus_by_document()
    count = sum(term in text for text in corpus.values())
    weight = 1.0 + math.log((len(corpus) + 1) / (count + 1))
    if term.isdigit() and len(term) == 4:
        return weight * 0.25
    return weight


def _query_focus(query: str) -> str:
    """Remove question scaffolding while retaining policy/service nouns."""

    focused = normalize(query)
    for phrase in INTENT_PHRASES:
        focused = focused.replace(phrase, "")
    return re.sub(r"[^a-z0-9\u3400-\u9fff]", "", focused)


def _query_coverage(query: str, document_text: str) -> float:
    """Estimate how much of the focused question is supported by one source."""

    focus = _query_focus(query)
    if not focus:
        return 0.0
    covered = [False] * len(focus)
    for size in (4, 3, 2):
        for start in range(len(focus) - size + 1):
            if all(covered[start:start + size]):
                continue
            if focus[start:start + size] in document_text:
                covered[start:start + size] = [True] * size
    return sum(covered) / len(covered)


def _quality_bonus(document: dict[str, Any]) -> float:
    """Prefer usable evidence only after the query has matched the document."""

    bonus = 0.0
    if document.get("parseStatus") == "parsed":
        bonus += 0.5
    if document.get("statusTone") == "current":
        bonus += 0.25
    return bonus


def _best_evidence_preview(
    document: dict[str, Any], query: str, matched_terms: list[str]
) -> str:
    """Return the chunk that best explains why a document matched."""

    chunks = document.get("evidenceChunks", [])
    if not chunks or not matched_terms:
        return ""

    def score(chunk: dict[str, Any]) -> tuple[float, int]:
        content = normalize(chunk.get("content", ""))
        matched = [term for term in matched_terms if term in content]
        focus = _query_focus(query)
        coverage = _query_coverage(focus, content)
        return (coverage * 100 + sum(len(term) ** 2 for term in matched), -len(content))

    best = max(chunks, key=score)
    return str(best.get("content", ""))[:800] if score(best)[0] > 0 else ""


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
    query: str,
    context: UserContext | None = None,
    limit: int = 5,
    version: str = "v4",
) -> list[dict[str, Any]]:
    """Rank documents and expose a score breakdown for debugging."""

    context = context or UserContext()
    try:
        preset = RETRIEVAL_PRESETS[version]
    except KeyError as error:
        raise ValueError(f"unknown retrieval version: {version}") from error
    terms = tokenize(query, preset.remove_intent_words)
    evidence_by_document = _evidence_text_by_document()
    results: list[dict[str, Any]] = []
    for document in load_knowledge_base().documents:
        score_info = _score_document_lexically(
            document, terms, evidence_by_document, preset, version, query, context,
        )
        if score_info is None:
            continue
        results.append(
            _build_search_result(document, score_info, version)
        )
    results.sort(
        key=lambda item: (-item["score"], str(item.get("date", ""))),
        reverse=False,
    )
    selected = results[:limit]
    for item in selected:
        document = load_knowledge_base().documents_by_id[item["id"]]
        item["evidencePreview"] = _best_evidence_preview(
            document, query, item["matchedTokens"]
        )
    return selected


@dataclass
class _ScoreInfo:
    """Intermediate scoring data before result dict construction."""

    lexical: float
    metadata: float
    quality: float
    coverage: float
    title_matches: list[str]
    body_matches: list[str]
    evidence_matches: list[str]


def _score_document_lexically(
    document: dict[str, Any],
    terms: list[str],
    evidence_by_document: dict[str, str],
    preset: RetrievalPreset,
    version: str,
    query: str,
    context: UserContext,
) -> _ScoreInfo | None:
    """Score one document against tokenised query terms, or ``None`` when the
    document has no match at all."""

    important, body = _document_text(document)
    evidence = evidence_by_document.get(document["id"], "")
    title_matches = [term for term in terms if term in important]
    body_matches = [term for term in terms if term in body and term not in title_matches]
    evidence_matches = [
        term for term in terms
        if term in evidence and term not in title_matches and term not in body_matches
    ]
    if version == "v4":
        lexical = (
            sum(_inverse_document_frequency(term) for term in title_matches)
            * preset.important_weight
            + sum(_inverse_document_frequency(term) for term in body_matches)
            * preset.body_weight
            + sum(_inverse_document_frequency(term) for term in evidence_matches)
            * preset.evidence_weight
        )
    else:
        lexical = (
            len(title_matches) * preset.important_weight
            + len(body_matches) * preset.body_weight
            + len(evidence_matches) * preset.evidence_weight
        )
    metadata = _context_bonus(document, context)
    quality = _quality_bonus(document) if lexical > 0 and preset.quality_bonus else 0.0
    coverage = _query_coverage(query, " ".join((important, body, evidence)))
    score = lexical + metadata + quality
    if score <= 0:
        return None
    return _ScoreInfo(
        lexical=lexical, metadata=metadata, quality=quality, coverage=coverage,
        title_matches=title_matches, body_matches=body_matches,
        evidence_matches=evidence_matches,
    )


def _build_search_result(
    document: dict[str, Any], info: _ScoreInfo, version: str
) -> dict[str, Any]:
    """Build the public result dict from pre-computed scoring data."""

    score = info.lexical + info.metadata + info.quality
    return {
        "id": document["id"],
        "title": document.get("title"),
        "category": document.get("category"),
        "issuer": document.get("issuer"),
        "date": document.get("date"),
        "status": document.get("status"),
        "score": round(score, 3),
        "scoreBreakdown": {
            "lexical": info.lexical,
            "metadata": info.metadata,
            "quality": info.quality,
            "semantic": 0,
            "queryCoverage": round(info.coverage, 4),
        },
        "matchedBy": [
            *(["domain_term"] if info.title_matches else []),
            *(["body_term"] if info.body_matches else []),
            *(["evidence_chunk"] if info.evidence_matches else []),
        ],
        "matchedTokens": info.title_matches + info.body_matches + info.evidence_matches,
        "excerpt": document.get("excerpt", ""),
        "keywords": document.get("keywords", ""),
        "note": document.get("note", ""),
        "evidencePreview": "",
        "retrievalVersion": version,
    }


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

    lexical = search_documents(
        query, context, max(limit, 20), version=settings.rag_retrieval_version
    )
    if not settings.rag_enable_semantic_search:
        return lexical[:limit], {
            "mode": "lexical", "fallback": None,
            "version": settings.rag_retrieval_version,
        }

    index = load_vector_index(settings.embedding_index_path)
    if not index:
        return lexical[:limit], {
            "mode": "lexical", "fallback": "index_missing",
            "version": settings.rag_retrieval_version,
        }

    try:
        query_vector = (await create_embeddings([query], settings))[0]
    except (httpx.HTTPError, ValueError) as error:
        return lexical[:limit], {
            "mode": "lexical",
            "fallback": "embedding_unavailable",
            "reason": type(error).__name__,
            "version": settings.rag_retrieval_version,
        }

    semantic_scores = {
        row["documentId"]: cosine_similarity(query_vector, row["values"])
        for row in index["vectors"]
    }
    return _merge_semantic_results(lexical, semantic_scores, limit, settings)


def _merge_semantic_results(
    lexical: list[dict[str, Any]],
    semantic_scores: dict[str, float],
    limit: int,
    settings: Settings,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Blend lexical and semantic scores into a unified ranking."""

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
                "scoreBreakdown": {
                    "lexical": 0, "metadata": 0, "quality": 0, "semantic": 0,
                },
                "matchedBy": [],
                "matchedTokens": [],
                "excerpt": document.get("excerpt", ""),
            },
        )
        lexical_normalized = min(
            item["scoreBreakdown"]["lexical"] / _LEXICAL_NORM_CEILING, 1
        )
        metadata_normalized = min(
            item["scoreBreakdown"]["metadata"] / _METADATA_NORM_CEILING, 1
        )
        item["scoreBreakdown"]["semantic"] = round(semantic, 4)
        item["score"] = round(
            lexical_normalized * _HYBRID_WEIGHT_LEXICAL
            + semantic * _HYBRID_WEIGHT_SEMANTIC
            + metadata_normalized * _HYBRID_WEIGHT_METADATA,
            4,
        )
        if semantic > 0:
            item["matchedBy"] = list(
                dict.fromkeys([*item["matchedBy"], "semantic_vector"])
            )

    results = sorted(by_id.values(), key=lambda item: item["score"], reverse=True)
    return results[:limit], {
        "mode": "hybrid",
        "fallback": None,
        "version": f"{settings.rag_retrieval_version}+embedding",
    }
