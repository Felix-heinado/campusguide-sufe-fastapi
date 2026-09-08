"""Small, dependency-free security boundaries for the HTTP API."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

from .config import Settings, get_settings


def require_admin(request: Request) -> None:
    """Require the configured operator key for management endpoints.

    The empty-key default keeps local/offline demos frictionless. Production
    deployments should set ``ADMIN_API_KEY``; comparisons are constant-time.
    """

    settings: Settings = getattr(request.app.state, "settings", get_settings())
    expected = settings.admin_api_key.strip()
    if not expected:
        return
    supplied = request.headers.get(settings.admin_api_key_header, "")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "ADMIN_AUTH_REQUIRED", "message": "需要管理员凭据"},
            headers={"WWW-Authenticate": "ApiKey"},
        )
