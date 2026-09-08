"""Feedback service: validate, anonymize, then persist user feedback."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from ..models import FeedbackArguments
from ..repositories.base import Repository


class FeedbackService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    async def record(self, arguments: FeedbackArguments) -> dict:
        """Hash the question so analytics do not store the original sentence."""

        feedback_id = str(uuid4())
        row = {
            "feedback_id": feedback_id,
            "question_hash": hashlib.sha256(arguments.question.encode("utf-8")).hexdigest(),
            "helpful": arguments.helpful,
            "reasons": arguments.reasons,
            "created_at": datetime.now(UTC),
        }
        await self.repository.insert_feedback(row)
        return {"accepted": True, "feedbackId": feedback_id}

