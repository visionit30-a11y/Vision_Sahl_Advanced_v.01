"""Cookie and CSRF request boundary for server-side sessions."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request, Response

from app.auth.sessions import SessionRecord, token_matches
from app.core.errors import AppError

SESSION_COOKIE = "__Host-sahl_session"
PREAUTH_COOKIE = "__Host-sahl_preauth"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CsrfRejectedError(AppError):
    code = "csrf_rejected"
    status_code = 403
    message = "The request could not be verified."


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


def validate_origin(request: Request, allowed_origins: set[str]) -> None:
    origin = request.headers.get("origin")
    if not origin or origin not in allowed_origins or urlsplit(origin).scheme != "https":
        raise CsrfRejectedError()


def validate_session_csrf(
    request: Request, session: SessionRecord, allowed_origins: set[str]
) -> None:
    if request.method.upper() not in UNSAFE_METHODS:
        return
    validate_origin(request, allowed_origins)
    supplied = request.headers.get(CSRF_HEADER)
    if not supplied or not token_matches(supplied, session.csrf_digest):
        raise CsrfRejectedError()
