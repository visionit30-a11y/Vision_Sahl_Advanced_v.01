"""Private runtime engine and platform-only connectivity probe."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.status import DependencyStatus

_settings = get_settings()

_engine = create_async_engine(
    _settings.database_url, pool_pre_ping=True, future=True, hide_parameters=True, echo=False
)


async def check_connection() -> DependencyStatus:
    """Probe the database with a trivial statement."""
    try:
        async with _engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - the probe reports, it does not raise
        return DependencyStatus(status="down", detail="Database connection unavailable.")
    return DependencyStatus(status="up")


async def dispose_engine() -> None:
    """Release pooled connections on shutdown."""
    await _engine.dispose()
