"""Constrained Tool Calling catalog.

The Agent or an API client may only call tools in ``TOOL_NAMES``. Each tool
validates its own arguments, which is safer than executing arbitrary model
output as code.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .knowledge_base import load_knowledge_base, public_document
from .models import FeedbackArguments, SearchRequest, UserContext
from .repositories.base import Repository
from .retrieval import get_evidence, search_documents
from .services.feedback import FeedbackService

TOOL_NAMES = ("search_documents", "get_document", "get_evidence", "record_feedback")


class ToolError(ValueError):
    """A user-correctable tool error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def call_tool(name: str, arguments: dict[str, Any], repository: Repository) -> dict:
    if name not in TOOL_NAMES:
        raise ToolError("UNKNOWN_TOOL", f"unknown tool: {name}")

    try:
        if name == "search_documents":
            request = SearchRequest.model_validate({
                "query": arguments.get("query", ""),
                "context": arguments.get("context", UserContext()),
                "limit": arguments.get("limit", 5),
            })
            return {"results": search_documents(request.query, request.context, request.limit)}

        if name == "get_document":
            document_id = str(arguments.get("documentId", "")).strip()
            if not document_id:
                raise ToolError("INVALID_ARGUMENT", "documentId is required")
            document = load_knowledge_base().documents_by_id.get(document_id)
            if not document:
                raise ToolError("DOCUMENT_NOT_FOUND", "document not found")
            return {"document": public_document(document)}

        if name == "get_evidence":
            chunk_id = str(arguments.get("chunkId", "")).strip()
            if not chunk_id:
                raise ToolError("INVALID_ARGUMENT", "chunkId is required")
            evidence = get_evidence(chunk_id)
            if not evidence:
                raise ToolError("EVIDENCE_NOT_FOUND", "evidence chunk not found")
            return {"evidence": evidence}

        feedback = FeedbackArguments.model_validate(arguments)
        return await FeedbackService(repository).record(feedback)
    except ValidationError as error:
        raise ToolError("INVALID_ARGUMENT", error.errors()[0]["msg"]) from error

