"""Optional embedding client and local vector index helpers."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import httpx

from .config import Settings


async def create_embeddings(texts: list[str], settings: Settings) -> list[list[float]]:
    """Call an OpenAI-compatible embedding endpoint with validated output."""

    if not settings.siliconflow_api_key:
        raise ValueError("SILICONFLOW_API_KEY is required for semantic retrieval")
    body = {
        "model": settings.siliconflow_embedding_model,
        "input": texts,
        "encoding_format": "float",
    }
    headers = {"Authorization": f"Bearer {settings.siliconflow_api_key}"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.siliconflow_base_url.rstrip('/')}/embeddings",
            headers=headers,
            json=body,
        )
        response.raise_for_status()
    rows = sorted(response.json().get("data", []), key=lambda row: row["index"])
    vectors = [row.get("embedding") for row in rows]
    if len(vectors) != len(texts) or any(not isinstance(vector, list) for vector in vectors):
        raise ValueError("embedding response does not match the input batch")
    return vectors


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Measure vector direction similarity in the range -1 to 1."""

    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def load_vector_index(path: Path) -> dict[str, Any] | None:
    """Return ``None`` when no index exists so lexical search can continue."""

    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        index = json.load(file)
    if not isinstance(index.get("vectors"), list):
        raise ValueError("vector index has an invalid structure")
    return index


def save_vector_index(path: Path, index: dict[str, Any]) -> None:
    """Replace the vector index atomically after a complete build."""

    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(index, file, ensure_ascii=False)
        file.flush()
    temporary.replace(path)
