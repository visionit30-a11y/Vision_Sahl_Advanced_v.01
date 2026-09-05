"""Health endpoint contract tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.cache.redis_client import redis_provider
from app.core.context import CORRELATION_ID_HEADER
from app.core.status import DependencyStatus
from app.services import health_service


async def test_application_health_is_independent_of_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["name"]
    assert body["version"]
    assert body["environment"]


async def test_health_response_carries_correlation_id(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.headers.get(CORRELATION_ID_HEADER)


async def test_correlation_id_from_request_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/health", headers={CORRELATION_ID_HEADER: "abc123"})

    assert response.headers[CORRELATION_ID_HEADER] == "abc123"


async def test_database_health_up(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_check() -> DependencyStatus:
        return DependencyStatus(status="up")

    monkeypatch.setattr(health_service, "check_connection", fake_check)

    response = await client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"dependency": "postgresql", "status": "up", "detail": None}


async def test_database_health_down_returns_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_check() -> DependencyStatus:
        return DependencyStatus(status="down", detail="OperationalError")

    monkeypatch.setattr(health_service, "check_connection", fake_check)

    response = await client.get("/health/db")

    assert response.status_code == 503
    assert response.json()["status"] == "down"


async def test_redis_disabled_is_reported_not_faked(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ping() -> DependencyStatus:
        return DependencyStatus(status="disabled", detail="Redis is not enabled.")

    monkeypatch.setattr(redis_provider, "ping", fake_ping)

    response = await client.get("/health/redis")

    assert response.status_code == 200
    body = response.json()
    assert body["dependency"] == "redis"
    assert body["status"] == "disabled"


async def test_redis_enabled_but_unreachable_returns_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ping() -> DependencyStatus:
        return DependencyStatus(status="down", detail="ConnectionError")

    monkeypatch.setattr(redis_provider, "ping", fake_ping)

    response = await client.get("/health/redis")

    assert response.status_code == 503
    assert response.json()["status"] == "down"
