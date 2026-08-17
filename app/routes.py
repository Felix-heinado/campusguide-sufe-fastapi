"""HTTP routes. Each route validates input, delegates work, and shapes output."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from .agent import run_agent
from .config import get_settings
from .dependencies import get_repository, get_task_service
from .knowledge_base import load_knowledge_base, public_document
from .models import ChatRequest, IngestionTaskRequest, SearchRequest, ToolCallRequest
from .repositories.base import Repository
from .retrieval import search_documents
from .services.tasks import TaskService
from .tools import TOOL_NAMES, ToolError, call_tool

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request) -> dict:
    base = load_knowledge_base()
    return {
        "status": "ok",
        "service": get_settings().service_name,
        "persistence": get_settings().persistence_backend,
        "requestId": request.state.request_id,
        "knowledgeBase": {
            "documents": len(base.documents),
            "evidenceChunks": len(base.evidence_chunks),
        },
    }


@router.get("/documents")
async def documents() -> dict:
    return {"documents": [public_document(item) for item in load_knowledge_base().documents]}


@router.get("/documents/{document_id}")
async def document(document_id: str) -> dict:
    item = load_knowledge_base().documents_by_id.get(document_id)
    if not item:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND"})
    return {"document": public_document(item)}


@router.post("/search")
async def search(request: SearchRequest) -> dict:
    return {
        "query": request.query,
        "results": search_documents(request.query, request.context, request.limit),
    }


@router.post("/chat")
async def chat(request: ChatRequest) -> dict:
    return run_agent(request)


@router.get("/tools")
async def tools() -> dict:
    return {"tools": [{"name": name} for name in TOOL_NAMES]}


@router.post("/tools/call")
async def tool_call(
    request: ToolCallRequest,
    repository: Repository = Depends(get_repository),
) -> dict:
    try:
        result = await call_tool(request.name, request.arguments, repository)
        return {"tool": request.name, "result": result}
    except ToolError as error:
        status_code = 404 if error.code.endswith("NOT_FOUND") else 400
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code, "message": str(error)},
        ) from error


@router.post("/ingestion/tasks", status_code=status.HTTP_202_ACCEPTED)
async def create_ingestion_task(
    request: IngestionTaskRequest,
    service: TaskService = Depends(get_task_service),
) -> dict:
    task = await service.create_task(request)
    return {"task": task.to_dict()}


@router.get("/ingestion/tasks/{task_id}")
async def ingestion_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
) -> dict:
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return {"task": task.to_dict()}

