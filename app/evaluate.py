"""Reproducible offline evaluation for retrieval and deterministic Agent flow."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, Settings, get_settings
from .model_provider import DeterministicModel
from .models import UserContext
from .question_policy import assess_question
from .retrieval import RETRIEVAL_PRESETS, hybrid_search_documents


def percentile(values: list[float], percent: float) -> float:
    """Return a linear-interpolated percentile without a heavy dependency."""

    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def result_text(results: list[dict[str, Any]]) -> str:
    """Build the observable text returned by retrieval."""

    return " ".join(
        str(item.get(field, ""))
        for item in results
        for field in (
            "title", "excerpt", "status", "keywords", "note",
            "evidencePreview", "matchedTokens",
        )
    )


async def evaluate_version(
    cases: list[dict[str, Any]], settings: Settings, version: str
) -> dict[str, Any]:
    model = DeterministicModel()
    expected_count = refusal_count = 0
    hit_at_1 = hit_at_5 = keyword_passes = tool_passes = refusal_correct = 0
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    details = []
    topic_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"cases": 0, "passed": 0}
    )

    version_settings = settings.model_copy(update={"rag_retrieval_version": version})
    for case in cases:
        started = time.perf_counter()
        results, retrieval = await hybrid_search_documents(
            case["question"], UserContext(), 5, version_settings
        )
        latency = (time.perf_counter() - started) * 1000
        latencies.append(latency)
        ids = [item["id"] for item in results]
        expected_ids = case.get("expected_document_ids", [])
        expected_keywords = case.get("expected_keywords", [])

        rank = None
        if expected_ids:
            expected_count += 1
            ranks = [
                ids.index(document_id) + 1
                for document_id in expected_ids
                if document_id in ids
            ]
            if ranks:
                rank = min(ranks)
                reciprocal_ranks.append(1 / rank)
                hit_at_5 += 1
                if rank == 1:
                    hit_at_1 += 1
            else:
                reciprocal_ranks.append(0.0)

        supported = [item for item in results if model._has_strong_evidence(item)]
        policy = assess_question(case["question"])
        refused = not policy.allowed or not supported
        refusal_ok = refused == case["should_refuse"]
        refusal_correct += int(refusal_ok)
        refusal_count += int(case["should_refuse"])

        searchable = result_text(results)
        matched_keywords = [word for word in expected_keywords if word in searchable]
        keyword_ok = not expected_keywords or len(matched_keywords) == len(expected_keywords)
        keyword_passes += int(keyword_ok)

        decision = await model.decide(
            [{"role": "user", "content": case["question"]}], []
        )
        actual_tool = (
            decision.tool_requests[0].name if decision.tool_requests else None
        )
        tool_ok = actual_tool == case.get("expected_tool")
        tool_passes += int(tool_ok)

        retrieval_ok = (rank is not None) if expected_ids else refused
        case_passed = retrieval_ok and refusal_ok and keyword_ok and tool_ok
        topic = case["topic"]
        topic_stats[topic]["cases"] += 1
        topic_stats[topic]["passed"] += int(case_passed)
        details.append({
            "question": case["question"], "topic": topic,
            "difficulty": case["difficulty"], "expectedDocumentIds": expected_ids,
            "topIds": ids, "rank": rank, "refused": refused,
            "matchedKeywords": matched_keywords, "missingKeywords": [
                word for word in expected_keywords if word not in searchable
            ],
            "tool": actual_tool, "passed": case_passed, "policyCode": policy.code,
            "latencyMs": round(latency, 3), "retrieval": retrieval,
        })

    count = len(cases)
    return {
        "version": version,
        "mode": details[0]["retrieval"]["mode"] if details else "unknown",
        "caseCount": count,
        "answerableCases": expected_count,
        "refusalCases": refusal_count,
        "hitAt1": round(hit_at_1 / expected_count, 4),
        "hitAt5": round(hit_at_5 / expected_count, 4),
        "meanReciprocalRank": round(statistics.mean(reciprocal_ranks), 4),
        "refusalAccuracy": round(refusal_correct / count, 4),
        "expectedKeywordCoverage": round(keyword_passes / count, 4),
        "expectedToolAccuracy": round(tool_passes / count, 4),
        "averageLatencyMs": round(statistics.mean(latencies), 3),
        "p95LatencyMs": round(percentile(latencies, 0.95), 3),
        "perTopic": {
            topic: {
                **row,
                "passRate": round(row["passed"] / row["cases"], 4),
            }
            for topic, row in sorted(topic_stats.items())
        },
        "failedCases": [item for item in details if not item["passed"]],
        "cases": details,
    }


def comparison_summary(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    previous: dict[str, Any] | None = None
    for report in reports:
        current_passed = {
            item["question"] for item in report["cases"] if item["passed"]
        }
        previous_passed = {
            item["question"] for item in previous["cases"] if item["passed"]
        } if previous else set()
        rows.append({
            "version": report["version"],
            "hitAt1": report["hitAt1"], "hitAt5": report["hitAt5"],
            "meanReciprocalRank": report["meanReciprocalRank"],
            "refusalAccuracy": report["refusalAccuracy"],
            "keywordCoverage": report["expectedKeywordCoverage"],
            "averageLatencyMs": report["averageLatencyMs"],
            "p95LatencyMs": report["p95LatencyMs"],
            "improvedCases": sorted(current_passed - previous_passed) if previous else [],
            "regressedCases": sorted(previous_passed - current_passed) if previous else [],
        })
        previous = report
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--versions", nargs="+", default=list(RETRIEVAL_PRESETS),
        choices=list(RETRIEVAL_PRESETS),
    )
    parser.add_argument(
        "--include-hybrid",
        action="store_true",
        help="also evaluate the configured embedding index and API provider",
    )
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/evaluation_latest.json")
    args = parser.parse_args()

    cases_path = PROJECT_ROOT / "data" / "evaluation_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    settings = get_settings().model_copy(update={"rag_enable_semantic_search": False})
    reports = [
        await evaluate_version(cases, settings, version) for version in args.versions
    ]
    if args.include_hybrid:
        hybrid_settings = get_settings().model_copy(update={
            "rag_enable_semantic_search": True,
            "rag_retrieval_version": "v4",
        })
        hybrid = await evaluate_version(cases, hybrid_settings, "v4")
        hybrid["version"] = "v5-hybrid"
        reports.append(hybrid)
    payload = {
        "scope": (
            "Offline regression set built from the repository knowledge snapshot; "
            "it is not a production user-satisfaction or real-LLM benchmark."
        ),
        "promptEvaluation": (
            "Prompt versions are protocol-tested offline. No real-model quality "
            "improvement is claimed without an external model evaluation."
        ),
        "comparison": comparison_summary(reports),
        "reports": reports,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload["comparison"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
