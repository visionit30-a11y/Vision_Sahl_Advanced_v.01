"""HTTP cookie, Origin, and synchronizer-token security gates."""

from __future__ import annotations

import pytest
from fastapi import Request, Response

from app.auth.http import (
    CsrfRejectedError,
    clear_session_cookie,
    set_session_cookie,
    validate_session_csrf,
)
from app.auth.sessions import MemorySessionStore, SessionService


async def _request(method: str, *, origin: str | None = None, csrf: str | None = None) -> Request:
    headers = []
    if origin:
        headers.append((b"origin", origin.encode()))
    if csrf:
        headers.append((b"x-csrf-token", csrf.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/",
            "headers": headers,
            "scheme": "https",
            "server": ("app.test", 443),
            "client": ("127.0.0.1", 1),
            "query_string": b"",
        }
    )


async def test_valid_csrf_and_allowed_origin() -> None:
    issued = await SessionService(MemorySessionStore()).issue(__import__("uuid").uuid4(), 1)
    request = await _request("POST", origin="https://app.test", csrf=issued.secrets.csrf_token)
    validate_session_csrf(request, issued.record, {"https://app.test"})


@pytest.mark.parametrize(
    "origin,csrf",
    [
        ("https://app.test", None),
        ("https://app.test", "invalid"),
        ("https://evil.test", "valid"),
        (None, "valid"),
        ("http://app.test", "valid"),
    ],
)
async def test_missing_invalid_csrf_or_denied_origin(origin: str | None, csrf: str | None) -> None:
    issued = await SessionService(MemorySessionStore()).issue(__import__("uuid").uuid4(), 1)
    supplied = issued.secrets.csrf_token if csrf == "valid" else csrf
    with pytest.raises(CsrfRejectedError):
        validate_session_csrf(
            await _request("POST", origin=origin, csrf=supplied),
            issued.record,
            {"https://app.test"},
        )


async def test_safe_request_does_not_require_csrf() -> None:
    issued = await SessionService(MemorySessionStore()).issue(__import__("uuid").uuid4(), 1)
    validate_session_csrf(await _request("GET"), issued.record, set())


def test_session_cookie_has_exact_security_attributes_and_no_domain() -> None:
    response = Response()
    set_session_cookie(response, "opaque")
    value = response.headers["set-cookie"]
    assert value.startswith("__Host-sahl_session=opaque;")
    for attribute in ("HttpOnly", "Path=/", "SameSite=lax", "Secure"):
        assert attribute in value
    assert "Domain=" not in value and "Max-Age=" not in value and "Expires=" not in value
    cleared = Response()
    clear_session_cookie(cleared)
    assert "Max-Age=0" in cleared.headers["set-cookie"]


def test_preauth_cookie_and_csrf_response_are_not_cacheable() -> None:
    from app.auth.http import expose_csrf_token, set_preauth_cookie

    response = Response()
    set_preauth_cookie(response, "opaque-state")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-sahl_preauth=opaque-state;")
    assert all(item in cookie for item in ("HttpOnly", "Path=/", "SameSite=lax", "Secure"))
    assert "Domain=" not in cookie
    exposed = Response()
    expose_csrf_token(exposed, "csrf-secret")
    assert exposed.headers["x-csrf-token"] == "csrf-secret"
    assert exposed.headers["cache-control"] == "no-store"
