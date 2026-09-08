"""Load the repository's independent JSON knowledge snapshot.

The Python service never imports JavaScript and never calls the Node.js
service.  Its only runtime input is this repository's own JSON file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .config import get_settings


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    documents: tuple[dict[str, Any], ...]
    evidence_chunks: tuple[dict[str, Any], ...]
    documents_by_id: dict[str, dict[str, Any]]
    chunks_by_id: dict[str, dict[str, Any]]


@lru_cache
def load_knowledge_base() -> KnowledgeBase:
    """Read and index the JSON snapshot once when the process needs it."""

    path = get_settings().knowledge_base_path
    with path.open("r", encoding="utf-8") as file:
        raw = json.load(file)

    documents = tuple(raw.get("documents", []))
    evidence_chunks = tuple(raw.get("evidenceChunks", []))
    return KnowledgeBase(
        documents=documents,
        evidence_chunks=evidence_chunks,
        documents_by_id={document["id"]: document for document in documents},
        chunks_by_id={chunk["chunkId"]: chunk for chunk in evidence_chunks},
    )


def public_document(document: dict[str, Any]) -> dict[str, Any]:
    """Return stable, public fields instead of leaking internal raw data."""

    allowed = (
        "id", "category", "title", "issuer", "date", "applies", "level",
        "status", "statusTone", "excerpt", "url", "verified", "sourceType",
        "sourceLabel", "note", "parseStatus",
    )
    return {key: document.get(key) for key in allowed if key in document}

