"""FastAPI application factory and process lifecycle."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .logging_config import configure_logging
from .model_provider import create_model_provider
from .repositories.base import Repository
from .repositories.factory import create_repository
from .routes import router
from .services.agent_runtime import AgentRuntime
from .services.tasks import TaskService

logger = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


def create_app(settings: Settings | None = None, repository: Repository | None = None) -> FastAPI:
    """Build an app with injectable dependencies for fast, deterministic tests."""

    settings = settings or get_settings()
    repository = repository or create_repository(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        await repository.start()
        task_service = TaskService(
            repository,
            worker_count=settings.task_workers,
            lease_seconds=settings.task_lease_seconds,
        )
        await task_service.start()
        app.state.repository = repository
        app.state.task_service = task_service
        app.state.agent_runtime = AgentRuntime(
            repository,
            create_model_provider(settings),
            settings,
        )
        try:
            yield
        finally:
            await task_service.close()
            await repository.close()

    app = FastAPI(
        title="SUFEGuide FastAPI Backend",
        version="0.1.0",
        description="Evidence-grounded campus Agent with readable engineering practices.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        """Attach a request ID and record enough context to diagnose failures."""

        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled request error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "request completed",
            extra={
                "request_id": request_id, "method": request.method,
                "path": request.url.path, "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    app.include_router(router)

    # The original SUFE Guide interface is shipped with the Python service.
    # Serving it from the same origin keeps local setup simple and avoids a
    # separate Node.js/Vite process or CORS configuration.
    if FRONTEND_DIR.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
        app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

        @app.get("/", include_in_schema=False)
        async def frontend() -> FileResponse:
            return FileResponse(FRONTEND_DIR / "index.html")
    else:
        @app.get("/")
        async def root() -> dict:
            return {"service": settings.service_name, "docs": "/docs", "health": "/api/health"}

    return app


app = create_app()
