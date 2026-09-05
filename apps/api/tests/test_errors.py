"""The unified error contract must hold for every failure."""

from __future__ import annotations

from httpx import AsyncClient


async def test_unknown_route_returns_unified_error(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_found"
    assert "correlation_id" in body["error"]
    assert "message" in body["error"]


async def test_error_body_never_contains_a_stack_trace(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert "Traceback" not in response.text
