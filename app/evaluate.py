"""Run a small, reproducible retrieval and refusal evaluation."""

from __future__ import annotations

import asyncio
import json
import time

from .config import PROJECT_ROOT, get_settings
from .model_provider import DeterministicModel
from .models import UserContext
from .retrieval import hybrid_search_documents


async def main() -> None:
    cases_path = PROJECT_ROOT / "data" / "evaluation_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    settings = get_settings()
    model = DeterministicModel()
    hits = 0
    top_hits = 0
    reciprocal_ranks: list[float] = []
    refusal_correct = 0
    latencies: list[float] = []
    details = []

    for case in cases:
        started = time.perf_counter()
        results, retrieval = await hybrid_search_documents(
            case["question"], UserContext(), 5, settings
        )
        latencies.append((time.perf_counter() - started) * 1000)
        ids = [item["id"] for item in results]
        if case["expected_document_id"] in ids:
            hits += 1
            rank = ids.index(case["expected_document_id"]) + 1
            reciprocal_ranks.append(1 / rank)
            if rank == 1:
                top_hits += 1
        supported = [item for item in results if model._has_strong_evidence(item)]
        refused = not supported
        if case["should_refuse"] == refused:
            refusal_correct += 1
        details.append({
            "question": case["question"],
            "topIds": ids,
            "refused": refused,
            "retrieval": retrieval,
        })

    expected_cases = [case for case in cases if case["expected_document_id"]]
    report = {
        "mode": details[0]["retrieval"]["mode"] if details else "unknown",
        "hitAt1": round(top_hits / len(expected_cases), 4),
        "hitAt5": round(hits / len(expected_cases), 4),
        "meanReciprocalRank": round(sum(reciprocal_ranks) / len(expected_cases), 4),
        "refusalAccuracy": round(refusal_correct / len(cases), 4),
        "averageLatencyMs": round(sum(latencies) / len(latencies), 3),
        "cases": details,
    }
    output = PROJECT_ROOT / "data" / "evaluation_latest.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
