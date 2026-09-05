"""Health probes.

Application health and dependency health are deliberately separate: a
dependency that is unavailable in a development environment does not make the
application itself unusable.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.cache.redis_client import redis_provider
from app.core.config import get_settings
from app.core.status import DependencyStatus
from app.db.session import check_connection


@dataclass(frozen=True)
class ApplicationHealth:
    """Liveness information about the application process itself."""

    name: str
    version: str
    environment: str


def application_health() -> ApplicationHealth:
    """Return application liveness. This never depends on external services."""
    settings = get_settings()
    return ApplicationHealth(
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
    )


async def database_health() -> DependencyStatus:
    """Probe PostgreSQL."""
    return await check_connection()


async def cache_health() -> DependencyStatus:
    """Probe Redis."""
    return await redis_provider.ping()
