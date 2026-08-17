"""Pydantic request and response models used by the public API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool, field_validator


class UserContext(BaseModel):
    """Optional metadata that can make retrieval more precise."""

    college: str = Field(default="", max_length=80)
    level: str = Field(default="", max_length=40)
    year: str = Field(default="", max_length=20)
    category: str = Field(default="", max_length=40)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    context: UserContext = Field(default_factory=UserContext)
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_cannot_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query cannot be blank")
        return value


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    context: UserContext = Field(default_factory=UserContext)

    @field_validator("question")
    @classmethod
    def question_cannot_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question cannot be blank")
        return value


class ToolCallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class FeedbackArguments(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    # StrictBool rejects strings such as "false". Without it, Pydantic would
    # coerce the string and silently accept a malformed Tool Calling payload.
    helpful: StrictBool
    reasons: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("reasons")
    @classmethod
    def clean_reasons(cls, reasons: list[str]) -> list[str]:
        return [reason.strip()[:200] for reason in reasons if reason.strip()]


class IngestionTaskRequest(BaseModel):
    source: str = Field(min_length=1, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=128)


TaskStatus = Literal["queued", "running", "succeeded", "failed"]
