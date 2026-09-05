"""Redis connection provider and health probe."""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.status import DependencyStatus


class RedisProvider:
    """Lazily creates a Redis client from configuration.

    When Redis is disabled for the current environment the provider returns no
    client at all. Callers must handle that explicitly; no fallback cache is
    provided on purpose.
    """

    def __init__(self, url: str, enabled: bool) -> None:
        self._url = url
        self._enabled = enabled
        self._client: Any = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def client(self) -> Any:
        """Return the Redis client, or None when Redis is disabled."""
        if not self._enabled:
            return None
        if self._client is None:
            self._client = Redis.from_url(self._url, decode_responses=True)
        return self._client

    async def ping(self) -> DependencyStatus:
        """Probe Redis. A disabled Redis is reported as such, never as healthy."""
        if not self._enabled:
            return DependencyStatus(
                status="disabled",
                detail="Redis is not enabled in this environment (see ADR-0003).",
            )
        client = self.client()
        try:
            await client.ping()
        except Exception as exc:  # noqa: BLE001 - the probe reports, it does not raise
            return DependencyStatus(status="down", detail=type(exc).__name__)
        return DependencyStatus(status="up")

    async def close(self) -> None:
        """Close the client on shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_settings = get_settings()

redis_provider = RedisProvider(url=_settings.redis_url, enabled=_settings.redis_enabled)
