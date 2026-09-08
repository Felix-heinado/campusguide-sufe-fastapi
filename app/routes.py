"""HTTP routes. Each route validates input, delegates work, and shapes output."""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from .agent import run_agent
from .config import get_settings
from .dependencies import get_agent_runtime, get_repository, get_task_service
from .knowledge_base import load_knowledge_base, public_document
from .models import (
    AgentRunRequest,
    ChatRequest,
    IngestionTaskRequest,
    SearchRequest,
    ToolCallRequest,
)
from .repositories.base import Repository
from .retrieval import search_documents
from .security import require_admin
from .services.agent_runtime import AgentRuntime, AgentRuntimeError, encode_sse
from .services.tasks import TaskService
from .tools import TOOL_NAMES, ToolError, call_tool

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


async def _record_search_event(
    request: Request,
    query: str,
    results: list[dict],
    mode: str,
    started: float,
) -> None:
    """Persist privacy-safe retrieval telemetry without storing question text."""

    try:
        await get_repository(request).record_search_event({
            "event_id": str(uuid4()),
            "request_id": request.state.request_id,
            "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "query_length": len(query),
            "result_count": len(results),
            "top_document_id": results[0]["id"] if results else None,
            "retrieval_mode": mode,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "created_at": datetime.now(UTC),
        })
    except Exception:
        # Observability must be best-effort; it must never take down a user
        # query because a migration is pending or the telemetry table is down.
        logger.warning(
            "search telemetry unavailable",
            exc_info=True,
            extra={"request_id": request.state.request_id},
        )


@router.get("/health", tags=["operations"])
async def health(request: Request) -> dict:
    base = load_knowledge_base()
    repository = get_repository(request)
    database = await repository.health_check()
    return {
        "status": "ok" if database["status"] == "ok" else "degraded",
        "service": get_settings().service_name,
        "persistence": get_settings().persistence_backend,
        "requestId": request.state.request_id,
        "knowledgeBase": {
            "documents": len(base.documents),
            "evidenceChunks": len(base.evidence_chunks),
        },
        "database": database,
        "rateLimiter": {"backend": request.app.state.rate_limiter.backend},
    }


@router.get("/ready", tags=["operations"])
async def ready(request: Request) -> dict:
    """Kubernetes/load-balancer readiness probe: DB must be reachable."""

    database = await get_repository(request).health_check()
    if database["status"] != "ok":
        raise HTTPException(status_code=503, detail={"code": "DATABASE_NOT_READY"})
    return {"status": "ready", "database": database}


@router.get("/metrics/summary", tags=["operations"])
async def metrics_summary(request: Request) -> dict:
    """Small privacy-safe operational view for a demo or internal dashboard."""

    require_admin(request)
    return {
        "service": get_settings().service_name,
        "stats": await get_repository(request).operational_stats(),
    }


@router.get("/documents", tags=["retrieval"])
async def documents() -> dict:
    return {"documents": [public_document(item) for item in load_knowledge_base().documents]}


@router.get("/documents/{document_id}", tags=["retrieval"])
async def document(document_id: str) -> dict:
    item = load_knowledge_base().documents_by_id.get(document_id)
    if not item:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND"})
    return {"document": public_document(item)}


@router.post("/search", tags=["retrieval"])
async def search(request: SearchRequest, http_request: Request) -> dict:
    started = time.perf_counter()
    results = search_documents(request.query, request.context, request.limit)
    await _record_search_event(http_request, request.query, results, "lexical", started)
    return {"query": request.query, "results": results}


@router.post("/chat", tags=["retrieval"])
async def chat(request: ChatRequest, http_request: Request) -> dict:
    started = time.perf_counter()
    result = run_agent(request)
    await _record_search_event(
        http_request, request.question, result.get("retrieval", []), "lexical-agent", started
    )
    return result


@router.post("/agent/run", tags=["agent"])
async def agent_run(
    request: AgentRunRequest,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> dict:
    """Run the full bounded Tool Calling loop and return one JSON response."""

    try:
        return await runtime.run(request)
    except AgentRuntimeError as error:
        status_code = 404 if error.code == "SESSION_NOT_FOUND" else 400
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code, "message": str(error)},
        ) from error


@router.post("/agent/stream", tags=["agent"])
async def agent_stream(
    request: AgentRunRequest,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> StreamingResponse:
    """Stream observable execution events using Server-Sent Events."""

    async def events():
        async for event in runtime.stream(request):
            yield encode_sse(event)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/tools", tags=["agent"])
async def tools() -> dict:
    return {"tools": [{"name": name} for name in TOOL_NAMES]}


@router.post("/tools/call", tags=["agent"])
async def tool_call(
    request: ToolCallRequest,
    repository: Repository = Depends(get_repository),
) -> dict:
    try:
        result = await call_tool(
            request.name,
            request.arguments,
            repository,
            get_settings(),
        )
        return {"tool": request.name, "result": result}
    except ToolError as error:
        status_code = 404 if error.code.endswith("NOT_FOUND") else 400
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code, "message": str(error)},
        ) from error


@router.post("/ingestion/tasks", status_code=status.HTTP_202_ACCEPTED, tags=["ingestion"])
async def create_ingestion_task(
    request: IngestionTaskRequest,
    http_request: Request,
    service: TaskService = Depends(get_task_service),
) -> dict:
    require_admin(http_request)
    task = await service.create_task(request)
    return {"task": task.to_dict()}


@router.get("/ingestion/tasks/{task_id}", tags=["ingestion"])
async def ingestion_task(
    task_id: str,
    request: Request,
    service: TaskService = Depends(get_task_service),
) -> dict:
    require_admin(request)
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return {"task": task.to_dict()}
