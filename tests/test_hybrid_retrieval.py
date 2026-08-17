from pathlib import Path

import pytest

from app.config import Settings
from app.embeddings import cosine_similarity
from app.models import UserContext
from app.retrieval import hybrid_search_documents


def test_cosine_similarity_is_easy_to_verify():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0)


@pytest.mark.asyncio
async def test_semantic_switch_falls_back_when_index_is_missing(tmp_path: Path):
    settings = Settings(
        rag_enable_semantic_search=True,
        embedding_index_path=tmp_path / "missing.json",
    )
    results, metadata = await hybrid_search_documents(
        "挂科重修", UserContext(), 5, settings
    )

    assert results[0]["id"] == "KB-2017-001"
    assert metadata == {"mode": "lexical", "fallback": "index_missing"}
