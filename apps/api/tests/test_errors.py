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


def test_importing_the_application_emits_no_starlette_deprecation() -> None:
    """The application must not read a name Starlette has deprecated.

    Written broader than the single constant that caused it: any deprecated
    Starlette name reached from our own modules fails here, so the next one is
    caught when it appears rather than when it is removed.
    """
    import importlib
    import warnings

    import app.core.errors

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(app.core.errors)

    offenders = [
        str(entry.message)
        for entry in caught
        if type(entry.message).__name__ == "StarletteDeprecationWarning"
    ]

    assert offenders == []
