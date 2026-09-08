import json

from app.config import PROJECT_ROOT
from app.knowledge_base import load_knowledge_base


def test_evaluation_set_is_large_and_references_real_documents():
    cases = json.loads(
        (PROJECT_ROOT / "data/evaluation_cases.json").read_text(encoding="utf-8")
    )
    document_ids = set(load_knowledge_base().documents_by_id)

    assert len(cases) >= 50
    assert sum(case["should_refuse"] for case in cases) >= 8
    assert all(set(case["expected_document_ids"]) <= document_ids for case in cases)
    assert all(case["expected_tool"] == "search_documents" for case in cases)


def test_evaluation_set_covers_multiple_topics_and_difficulties():
    cases = json.loads(
        (PROJECT_ROOT / "data/evaluation_cases.json").read_text(encoding="utf-8")
    )

    assert len({case["topic"] for case in cases}) >= 8
    assert {case["difficulty"] for case in cases} == {"easy", "medium", "hard"}
