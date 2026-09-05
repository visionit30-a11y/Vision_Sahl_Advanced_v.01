"""Health endpoints.

    GET /health         application liveness - always 200 while the process runs
    GET /health/db      PostgreSQL dependency probe
    GET /health/redis   Redis dependency probe

A dependency that is intentionally disabled reports "disabled" with HTTP 200;
a dependency that is enabled but unreachable reports "down" with HTTP 503.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.core.status import DependencyState
from app.services.health_service import application_health, cache_health, database_health

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Application liveness payload."""

    status: str = Field(default="ok", examples=["ok"])
    name: str
    version: str
    environment: str


class DependencyHealthResponse(BaseModel):
    """Dependency probe payload."""

    dependency: str
    status: DependencyState
    detail: str | None = None


@router.get("/health", response_model=HealthResponse, summary="Application health")
async def read_health() -> HealthResponse:
    """Return application liveness without touching any external dependency."""
    health = application_health()
    return HealthResponse(
        status="ok",
        name=health.name,
        version=health.version,
        environment=health.environment,
    )


@router.get(
    "/health/db",
    response_model=DependencyHealthResponse,
    summary="PostgreSQL health",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Database unreachable"}},
)
async def read_database_health(response: Response) -> DependencyHealthResponse:
    """Probe the PostgreSQL connection."""
    result = await database_health()
    if result.is_failure:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DependencyHealthResponse(
        dependency="postgresql", status=result.status, detail=result.detail
    )


@router.get(
    "/health/redis",
    response_model=DependencyHealthResponse,
    summary="Redis health",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Redis unreachable"}},
)
async def read_cache_health(response: Response) -> DependencyHealthResponse:
    """Probe Redis. Disabled is a configuration state, not a failure."""
    result = await cache_health()
    if result.is_failure:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DependencyHealthResponse(
        dependency="redis", status=result.status, detail=result.detail
    )
