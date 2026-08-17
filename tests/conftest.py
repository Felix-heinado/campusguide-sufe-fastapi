from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repositories.json_store import JsonRepository


@pytest.fixture
def repository(tmp_path: Path) -> JsonRepository:
    return JsonRepository(tmp_path / "feedback.json", tmp_path / "tasks.json")


@pytest.fixture
def client(repository: JsonRepository):
    settings = Settings(persistence_backend="json", task_workers=2, task_lease_seconds=5)
    with TestClient(create_app(settings=settings, repository=repository)) as test_client:
        yield test_client

