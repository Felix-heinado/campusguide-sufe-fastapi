from pathlib import Path

import pytest

from app.config import Settings
from app.embeddings import cosine_similarity
from app.models import UserContext
from app.retrieval import hybrid_search_documents, search_documents


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
    assert metadata == {
        "mode": "lexical", "fallback": "index_missing", "version": "v4"
    }


def test_v4_retrieves_parsed_rules_for_short_policy_queries():
    results = search_documents("本科生申请缓考有什么规定", limit=5, version="v4")

    assert "OFFICIAL-REG-026" in [item["id"] for item in results]
    assert any("缓考" in item["evidencePreview"] for item in results)


def test_v4_exposes_score_breakdown_and_query_coverage():
    result = search_documents("校园一卡通补办", limit=1, version="v4")[0]

    assert result["id"] == "KB-SERVICE-001"
    assert result["scoreBreakdown"]["queryCoverage"] > 0
    assert result["retrievalVersion"] == "v4"


def test_unknown_retrieval_version_fails_fast():
    with pytest.raises(ValueError, match="unknown retrieval version"):
        search_documents("挂科", version="v99")
