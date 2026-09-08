# ruff: noqa: F811
"""Real database login with one-use preauth and generic credential failures."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.routes import auth_sessions
from app.auth.sessions import token_digest
from app.core.errors import register_exception_handlers
from app.db import auth_http
from tests.db.test_auth_audit_wiring import PASSWORD, AuthEventFixture, auth_events  # noqa: F401


@pytest.mark.parametrize(
    "mode", ["valid", "wrong", "missing_user", "missing_csrf", "invalid_csrf", "foreign_origin"]
)
async def test_real_login_and_preauth_replay(
    auth_events: AuthEventFixture, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from app.core.config import Settings

    config = Settings(
        app_env="test",
        auth_local_http_origin="http://localhost:5187",
        auth_hmac_key="x" * 32,
    )
    monkeypatch.setattr(auth_http, "_engine", auth_events.runtime)
    monkeypatch.setattr(auth_http, "_password_authentication", lambda: auth_events.service)
    monkeypatch.setattr(auth_http, "get_settings", lambda: config)
    monkeypatch.setattr(auth_sessions, "get_settings", lambda: config)
    app = FastAPI()
    app.include_router(auth_sessions.router)
    register_exception_handlers(app)
    async with AsyncClient(
        transport=ASGITransport(app, client=(str(uuid.uuid4()), 1)), base_url="https://app.test"
    ) as client:
        headers = {"Origin": "http://localhost:5187"}
        bootstrap = await client.get("/auth/preauth", headers=headers)
        assert bootstrap.status_code == 204
        state_token = client.cookies.get("__Host-sahl_preauth")
        assert state_token is not None
        state_digest = token_digest(state_token)
        headers["X-CSRF-Token"] = bootstrap.headers["X-CSRF-Token"]
        payload = {
            "email": "absent-" + auth_events.email if mode == "missing_user" else auth_events.email,
            "password": "wrong password value" if mode == "wrong" else PASSWORD,
        }
        if mode == "missing_csrf":
            headers.pop("X-CSRF-Token")
        elif mode == "invalid_csrf":
            headers["X-CSRF-Token"] = "invalid"
        elif mode == "foreign_origin":
            headers["Origin"] = "https://foreign.example"
        response = await client.post("/auth/login", headers=headers, json=payload)
        expected = 204 if mode == "valid" else (401 if mode in {"wrong", "missing_user"} else 403)
        assert response.status_code == expected
        assert PASSWORD not in response.text
        if mode == "valid":
            assert "HttpOnly" in response.headers["set-cookie"]
            assert (await client.get("/auth/me")).status_code == 200
        replay = await client.post("/auth/login", headers=headers, json=payload)
        assert replay.status_code == 403
    with auth_events.migrator.begin() as db:
        db.execute(
            text("DELETE FROM auth.preauth_csrf_states WHERE state_digest=:digest"),
            {"digest": state_digest},
        )
