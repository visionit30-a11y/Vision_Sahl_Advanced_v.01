"""Cookie and CSRF request boundary for server-side sessions."""

from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

from fastapi import Request, Response

from app.auth.sessions import SessionRecord, token_matches
from app.auth.tenants import SessionRejectedError
from app.core.errors import AppError

SESSION_COOKIE = "__Host-sahl_session"
PREAUTH_COOKIE = "__Host-sahl_preauth"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)


class CsrfRejectedError(AppError):
    code = "csrf_rejected"
    status_code = 403
    message = "The request could not be verified."


class TenantContextChangedError(AppError):
    code = "tenant_context_changed"
    status_code = 409
    message = "The trusted tenant context changed."


def require_session_bearer(bearer: str) -> str:
    if not _TOKEN_PATTERN.fullmatch(bearer):
        raise SessionRejectedError()
    return bearer


def set_session_cookie(response: Response, bearer: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, bearer, secure=True, httponly=True, samesite="lax", path="/"
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax", path="/")


def set_preauth_cookie(response: Response, state_token: str) -> None:
    response.set_cookie(
        PREAUTH_COOKIE, state_token, secure=True, httponly=True, samesite="lax", path="/"
    )


def clear_preauth_cookie(response: Response) -> None:
    response.delete_cookie(PREAUTH_COOKIE, secure=True, httponly=True, samesite="lax", path="/")


def expose_csrf_token(response: Response, csrf_token: str) -> None:
    response.headers[CSRF_HEADER] = csrf_token
    response.headers["Cache-Control"] = "no-store"


def _allowed_origin(origin: str, allowed_origins: set[str], local_http_origin: str | None) -> bool:
    if origin not in allowed_origins:
        return False
    return urlsplit(origin).scheme == "https" or (
        local_http_origin == "http://localhost:5187" and origin == local_http_origin
    )


def validate_origin(
    request: Request, allowed_origins: set[str], *, local_http_origin: str | None = None
) -> None:
    origin = request.headers.get("origin")
    if not origin or not _allowed_origin(origin, allowed_origins, local_http_origin):
        raise CsrfRejectedError()


def validate_csrf_bootstrap_origin(
    request: Request, allowed_origins: set[str], *, local_http_origin: str | None = None
) -> None:
    """Only a same-origin browser fetch can renew the session's synchronizer token."""
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site != "same-origin":
        raise CsrfRejectedError()
    if request.headers.get("origin"):
        validate_origin(request, allowed_origins, local_http_origin=local_http_origin)
        return
    origin = str(request.base_url).rstrip("/")
    if fetch_site != "same-origin" or not _allowed_origin(
        origin, allowed_origins, local_http_origin
    ):
        raise CsrfRejectedError()


def validate_session_csrf(
    request: Request,
    session: SessionRecord,
    allowed_origins: set[str],
    *,
    local_http_origin: str | None = None,
) -> None:
    if request.method.upper() not in UNSAFE_METHODS:
        return
    validate_origin(request, allowed_origins, local_http_origin=local_http_origin)
    supplied = request.headers.get(CSRF_HEADER)
    if (
        not supplied
        or not _TOKEN_PATTERN.fullmatch(supplied)
        or not token_matches(supplied, session.csrf_digest)
    ):
        raise CsrfRejectedError()


def validate_expected_membership(request: Request, membership_id: uuid.UUID | None) -> None:
    """A client hint detects stale tabs; it never establishes tenant authority."""
    if request.method.upper() not in UNSAFE_METHODS:
        return
    expected = request.headers.get("X-Expected-Membership-ID")
    if membership_id is None and expected is None:
        return
    if not expected:
        raise CsrfRejectedError()
    try:
        expected_id = uuid.UUID(expected)
    except ValueError:
        raise CsrfRejectedError() from None
    if expected_id != membership_id:
        raise TenantContextChangedError()
