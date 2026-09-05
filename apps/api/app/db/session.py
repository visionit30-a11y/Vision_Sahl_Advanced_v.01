"""Async engine, session factory and connectivity probe."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.status import DependencyStatus

_settings = get_settings()

engine = create_async_engine(_settings.database_url, pool_pre_ping=True, future=True)

SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a database session."""
    async with SessionFactory() as session:
        yield session


async def check_connection() -> DependencyStatus:
    """Probe the database with a trivial statement."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - the probe reports, it does not raise
        return DependencyStatus(status="down", detail=type(exc).__name__)
    return DependencyStatus(status="up")


async def dispose_engine() -> None:
    """Release pooled connections on shutdown."""
    await engine.dispose()
