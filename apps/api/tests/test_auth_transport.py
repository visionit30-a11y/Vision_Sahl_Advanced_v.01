"""Production auth route and request-boundary regression tests."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api import authorization_dependencies
from app.auth.http import (
    CsrfRejectedError,
    require_session_bearer,
    validate_csrf_bootstrap_origin,
    validate_origin,
)
from app.auth.sessions import SessionRecord, token_digest
from app.auth.tenants import AuthenticatedPrincipal, SessionRejectedError, TrustedTenantAccess
from app.authorization.service import AuthorizationDecision
from app.core.config import Settings
from app.db.auth_http import SessionIdentity, _bootstrap_token, auth_http_service
from app.models.tenant import TenantId
from app.tenancy.context import TenantContext
from app.ui_settings.contracts import StoredUiSettingsPatch, UiSettingsPatch
from app.ui_settings.service import ui_settings_service

BEARER = "a" * 43
CSRF = "b" * 43
LOCAL_ORIGIN = "http://localhost:5187"


def _request(
    *,
    origin: str | None = None,
    fetch_site: str | None = None,
    method: str = "GET",
) -> Request:
    headers = [(b"host", b"localhost:5187")]
    if origin:
        headers.append((b"origin", origin.encode()))
    if fetch_site:
        headers.append((b"sec-fetch-site", fetch_site.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/auth/csrf",
            "headers": headers,
            "scheme": "http",
            "server": ("localhost", 5187),
            "client": ("127.0.0.1", 12345),
            "query_string": b"",
        }
    )


def _access() -> TrustedTenantAccess:
    user, session, membership, tenant = (uuid.uuid7() for _ in range(4))
    now = datetime.now(UTC)
    record = SessionRecord(
        session,
        user,
        token_digest(BEARER),
        token_digest(CSRF),
        1,
        now,
        now,
        now,
        now + timedelta(minutes=30),
        now + timedelta(hours=8),
        selected_membership_id=membership,
        selected_membership_version=1,
    )
    return TrustedTenantAccess(
        AuthenticatedPrincipal(user, session, membership, 1),
        TenantContext(TenantId(tenant)),
        record,
    )


def test_auth_session_routes_are_registered_on_real_application(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    for path, method in (
        ("/auth/me", "get"),
        ("/auth/memberships", "get"),
        ("/auth/csrf", "get"),
        ("/auth/tenant/switch", "post"),
        ("/auth/logout", "post"),
        ("/auth/login", "post"),
        ("/auth/preauth", "get"),
    ):
        assert method in paths[path]
    assert not any("/auth/test/" in path for path in paths)
    assert "/auth/password/reset" not in paths


@pytest.mark.parametrize("path", ["/auth/me", "/auth/memberships", "/auth/csrf"])
async def test_auth_routes_reject_missing_session_and_are_not_cacheable(
    client: AsyncClient, path: str
) -> None:
    response = await client.get(path)
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"


async def test_me_serializes_only_identity_projection(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = SessionIdentity(uuid.uuid7(), "member@example.test", uuid.uuid7())
    identity_response = AsyncMock(return_value=identity)
    monkeypatch.setattr(
        type(auth_http_service), "me", lambda self, bearer: identity_response(bearer)
    )
    response = await client.get("/auth/me", headers={"Cookie": f"__Host-sahl_session={BEARER}"})
    assert response.status_code == 200
    assert response.json() == {
        "id": str(identity.id),
        "email": identity.email,
        "selectedMembershipId": str(identity.selected_membership_id),
    }
    assert BEARER not in response.text
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("secret", ["bad", "\u2603", "x" * 44, "x" * 42, "x" * 42 + "+"])
def test_malformed_bearers_are_sanitized(secret: str) -> None:
    with pytest.raises(SessionRejectedError) as caught:
        require_session_bearer(secret)
    assert secret not in str(caught.value)


def test_bootstrap_token_is_stable_distinct_and_bearer_bound() -> None:
    token = _bootstrap_token(BEARER)
    assert len(token) == 43
    assert token == _bootstrap_token(BEARER)
    assert token != BEARER
    assert token != _bootstrap_token("c" * 43)


@pytest.mark.parametrize(
    "origin,fetch_site,local_enabled,allowed",
    [
        (None, "same-origin", True, True),
        (LOCAL_ORIGIN, "same-origin", True, True),
        (LOCAL_ORIGIN, "cross-site", True, False),
        ("https://foreign.test", "same-origin", True, False),
        (None, None, True, False),
        (LOCAL_ORIGIN, None, False, False),
    ],
)
def test_csrf_bootstrap_requires_same_origin_and_explicit_local_opt_in(
    origin: str | None, fetch_site: str | None, local_enabled: bool, allowed: bool
) -> None:
    request = _request(origin=origin, fetch_site=fetch_site)
    if allowed:
        validate_csrf_bootstrap_origin(
            request, {LOCAL_ORIGIN}, local_http_origin=LOCAL_ORIGIN if local_enabled else None
        )
    else:
        with pytest.raises(CsrfRejectedError):
            validate_csrf_bootstrap_origin(
                request,
                {LOCAL_ORIGIN},
                local_http_origin=LOCAL_ORIGIN if local_enabled else None,
            )


def test_nonlocal_http_is_never_an_origin_exception() -> None:
    with pytest.raises(CsrfRejectedError):
        validate_origin(
            _request(origin="http://foreign.test"),
            {"http://foreign.test"},
            local_http_origin="http://foreign.test",
        )


async def test_csrf_rejects_foreign_origin_before_bootstrap(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap = AsyncMock()
    monkeypatch.setattr(
        type(auth_http_service), "bootstrap_csrf", lambda self, *args: bootstrap(*args)
    )
    response = await client.get(
        "/auth/csrf",
        headers={
            "Cookie": f"__Host-sahl_session={BEARER}",
            "Origin": "https://foreign.test",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert response.status_code == 403
    bootstrap.assert_not_called()
    assert response.headers["Cache-Control"] == "no-store"


async def test_switch_rejects_extra_selectors_and_redacts_validation_input(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    switch = AsyncMock()
    monkeypatch.setattr(type(auth_http_service), "switch", lambda self, *args: switch(*args))
    response = await client.post(
        "/auth/tenant/switch",
        headers={"Cookie": f"__Host-sahl_session={BEARER}"},
        json={"membership_id": str(uuid.uuid7()), "tenant_id": "sensitive-selector"},
    )
    assert response.status_code == 422
    assert "sensitive-selector" not in response.text
    switch.assert_not_called()


@pytest.mark.parametrize(
    "scenario,status",
    [
        ("valid", 200),
        ("missing_csrf", 403),
        ("invalid_csrf", 403),
        ("foreign_origin", 403),
        ("missing_expected", 403),
        ("invalid_expected", 403),
        ("stale_expected", 409),
        ("permission_denied", 403),
    ],
)
async def test_real_ui_settings_dependency_enforces_csrf_origin_and_stale_tab_before_write(
    app: FastAPI,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    status: int,
) -> None:
    access = _access()
    monkeypatch.setattr(
        authorization_dependencies,
        "trusted_access_from_bearer",
        AsyncMock(return_value=access),
    )
    local = Settings(app_env="test", auth_local_http_origin=LOCAL_ORIGIN)
    monkeypatch.setattr(authorization_dependencies, "get_settings", lambda: local)
    app.dependency_overrides[authorization_dependencies.get_security_denial_auditor] = lambda: (
        AsyncMock()
    )
    authorizer = AsyncMock()
    authorizer.authorize.return_value = (
        AuthorizationDecision.DENY
        if scenario == "permission_denied"
        else AuthorizationDecision.ALLOW
    )
    app.dependency_overrides[authorization_dependencies.get_authorization_service] = lambda: (
        authorizer
    )
    record = StoredUiSettingsPatch(UiSettingsPatch.model_validate({"theme": "teal-calm"}), 1)
    write = AsyncMock(return_value=record)
    monkeypatch.setattr(type(ui_settings_service), "put_user", lambda self, *args: write(*args))
    headers = {
        "Cookie": f"__Host-sahl_session={BEARER}",
        "Origin": LOCAL_ORIGIN,
        "X-CSRF-Token": CSRF,
        "X-Expected-Membership-ID": str(access.principal.membership_id),
    }
    if scenario == "missing_csrf":
        del headers["X-CSRF-Token"]
    elif scenario == "invalid_csrf":
        headers["X-CSRF-Token"] = "bad"
    elif scenario == "foreign_origin":
        headers["Origin"] = "https://foreign.test"
    elif scenario == "missing_expected":
        del headers["X-Expected-Membership-ID"]
    elif scenario == "invalid_expected":
        headers["X-Expected-Membership-ID"] = "bad"
    elif scenario == "stale_expected":
        headers["X-Expected-Membership-ID"] = str(uuid.uuid7())
    response = await client.put(
        "/ui-settings/user",
        headers=headers,
        json={"settings": {"theme": "teal-calm"}, "expected_version": None},
    )
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store"
    if status == 200:
        write.assert_awaited_once()
    else:
        write.assert_not_called()
        assert BEARER not in response.text and CSRF not in response.text
    if status == 409:
        assert response.headers["X-Auth-Error"] == "tenant_context_changed"


async def test_logout_clears_secure_cookie(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    logout_response = AsyncMock(return_value=None)
    monkeypatch.setattr(
        type(auth_http_service), "logout", lambda self, *args: logout_response(*args)
    )
    response = await client.post(
        "/auth/logout", headers={"Cookie": f"__Host-sahl_session={BEARER}"}
    )
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert all(item in cookie for item in ("Max-Age=0", "HttpOnly", "Secure", "SameSite=lax"))
    assert "Domain=" not in cookie


def test_session_dataclass_repr_does_not_expose_secrets() -> None:
    record = replace(_access().session, csrf_digest=token_digest(CSRF))
    assert BEARER not in repr(record)
    assert CSRF not in repr(record)


def test_config_repr_does_not_expose_auth_hmac_key() -> None:
    key = "test-only-auth-key-not-for-production"
    settings = Settings(auth_hmac_key=key)
    assert key not in repr(settings)
    assert key not in str(settings)
    assert settings.required_auth_hmac_key == key.encode()


def test_startup_validation_error_does_not_echo_auth_hmac_key() -> None:
    key = "test-only-sensitive-startup-key"
    with pytest.raises(ValidationError) as caught:
        Settings(
            app_env="production",
            auth_local_http_origin=LOCAL_ORIGIN,
            auth_hmac_key=key,
        )
    assert key not in str(caught.value)
    assert "input_value=" not in str(caught.value)


@pytest.mark.parametrize("path", ["/auth/me", "/ui-settings/effective"])
async def test_unexpected_errors_are_sanitized_and_not_cacheable(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    private_detail = "internal-test-detail-not-for-response"

    async def fail_dependency() -> TrustedTenantAccess:
        raise RuntimeError(private_detail)

    async def fail_identity(self: object, bearer: str) -> SessionIdentity:
        raise RuntimeError(private_detail)

    app.dependency_overrides[authorization_dependencies.require_authenticated_access] = (
        fail_dependency
    )
    monkeypatch.setattr(type(auth_http_service), "me", fail_identity)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get(path, headers={"Cookie": f"__Host-sahl_session={BEARER}"})
    assert response.status_code == 500
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.json()["error"]["code"] == "internal_error"
    assert private_detail not in response.text
    assert BEARER not in response.text
