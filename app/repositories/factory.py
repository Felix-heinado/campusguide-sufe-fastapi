"""Choose the configured persistence implementation in one place."""

from ..config import Settings
from .base import Repository
from .json_store import JsonRepository
from .mysql import MySQLRepository


def create_repository(settings: Settings) -> Repository:
    if settings.persistence_backend.lower() == "mysql":
        return MySQLRepository(settings)
    return JsonRepository(settings.feedback_path, settings.task_path)

