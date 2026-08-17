"""Application settings.

The project reads configuration from environment variables instead of hard
coding passwords or machine-specific paths.  Keeping all settings here makes
it easy to answer the interview question: "Where would you change a timeout?"
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Typed configuration loaded from ``.env`` and the process environment."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "campusguide-sufe-fastapi"
    # MySQL is the main implementation. Tests explicitly inject JsonRepository
    # so they stay fast and do not require a developer's local database.
    persistence_backend: str = "mysql"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "campusguide_app"
    mysql_password: str = ""
    mysql_database: str = "campusguide_fastapi"

    task_workers: int = 2
    task_lease_seconds: int = 30
    task_poll_seconds: float = 0.5

    rag_enable_semantic_search: bool = False
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_embedding_model: str = "Qwen/Qwen3-Embedding-4B"

    @property
    def knowledge_base_path(self) -> Path:
        return PROJECT_ROOT / "data" / "knowledge_base.json"

    @property
    def feedback_path(self) -> Path:
        return PROJECT_ROOT / "data" / "feedback.json"

    @property
    def task_path(self) -> Path:
        return PROJECT_ROOT / "data" / "ingestion_tasks.json"


@lru_cache
def get_settings() -> Settings:
    """Create settings once per process so all modules see the same values."""

    return Settings()
