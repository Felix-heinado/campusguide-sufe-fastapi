"""FastAPI dependency helpers kept separate to avoid global hidden state."""

from fastapi import Request

from .repositories.base import Repository
from .services.tasks import TaskService


def get_repository(request: Request) -> Repository:
    return request.app.state.repository


def get_task_service(request: Request) -> TaskService:
    return request.app.state.task_service

