"""Liveness and readiness endpoints.

The two are deliberately separate. A platform health check that touches the
database will take the whole service out of rotation during a brief database
blip, so ``/health`` answers from the process alone and ``/health/ready``
is the one that reports on dependencies.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fai.core.config import settings
from fai.core.logging import get_logger
from fai.db.session import get_db

router = APIRouter(tags=["health"])
log = get_logger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    environment: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Report that the process is running. Touches no dependency."""
    return HealthResponse(status="ok", environment=settings.environment, version="0.1.0")


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadinessResponse:
    """Report on each dependency the service needs to serve real traffic."""
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        log.warning("readiness_check_failed", check="database", error=str(exc))
        checks["database"] = "error"

    try:
        result = await db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        checks["pgvector"] = "ok" if result.first() is not None else "missing"
    except Exception as exc:
        log.warning("readiness_check_failed", check="pgvector", error=str(exc))
        checks["pgvector"] = "error"

    ready = all(value == "ok" for value in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ready else "degraded", checks=checks)
