"""Session cookie dependency and secret-redaction tests."""

from __future__ import annotations

import pytest
from fastapi import Request

from app.api.auth_dependencies import InvalidSessionError, session_bearer_from_cookie
from app.core.errors import build_error_payload
from app.core.logging import MASK, _redact_sensitive


def _request(cookie: str | None = None) -> Request:
    headers = [] if cookie is None else [(b"cookie", cookie.encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "scheme": "https",
            "server": ("app.test", 443),
            "client": ("127.0.0.1", 1),
            "query_string": b"",
        }
    )


def test_session_dependency_reads_cookie_without_persistence() -> None:
    assert session_bearer_from_cookie(_request("__Host-sahl_session=opaque")) == "opaque"
    with pytest.raises(InvalidSessionError, match="Authentication is required"):
        session_bearer_from_cookie(_request())


def test_bearer_csrf_cookie_and_state_are_redacted_recursively() -> None:
    values = {
        "bearer": "raw-secret-value",
        "nested": {"x-csrf-token": "csrf-secret-value", "state_token": "state-secret-value"},
        "cookie": "__Host-sahl_session=cookie-secret-value",
    }
    redacted = _redact_sensitive(None, "info", values)
    assert redacted == {
        "bearer": MASK,
        "nested": {"x-csrf-token": MASK, "state_token": MASK},
        "cookie": MASK,
    }
    assert all(
        secret not in repr(redacted)
        for secret in (
            "raw-secret-value",
            "csrf-secret-value",
            "state-secret-value",
            "cookie-secret-value",
        )
    )


def test_error_details_do_not_echo_bearer_or_csrf() -> None:
    payload = build_error_payload(
        "bad",
        "Rejected",
        {"bearer": "raw-secret-value", "csrf_token": "csrf-secret-value"},
    )
    assert "raw-secret-value" not in repr(payload)
    assert "csrf-secret-value" not in repr(payload)


def test_auth_backend_never_uses_browser_storage() -> None:
    from pathlib import Path

    auth_root = Path(__file__).parents[1] / "app" / "auth"
    source = "\n".join(path.read_text(encoding="utf-8") for path in auth_root.glob("*.py"))
    assert "localStorage" not in source and "sessionStorage" not in source
