"""Shared test fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytest_plugins = ["tests.security_gate"]


def pytest_asyncio_loop_factories() -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    """Use Psycopg-compatible loops without deprecated event-loop policies.

    Windows defaults to Proactor, which Psycopg async cannot use. A selector
    matches the local Uvicorn --reload worker and the Linux default in CI.
    pytest-asyncio owns creation and cleanup through its loop-factory hook.
    """
    return {"selector": asyncio.SelectorEventLoop}


@pytest.fixture
def app() -> FastAPI:
    """A fresh application instance for each test."""
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client wired directly to the ASGI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
