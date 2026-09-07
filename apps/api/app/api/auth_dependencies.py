"""Authentication transport dependencies without tenant resolution."""

from __future__ import annotations

from fastapi import Request

from app.auth.http import SESSION_COOKIE
from app.core.errors import AppError


class InvalidSessionError(AppError):
    code = "invalid_session"
    status_code = 401
    message = "Authentication is required."


def session_bearer_from_cookie(request: Request) -> str:
    bearer = request.cookies.get(SESSION_COOKIE)
    if not bearer:
        raise InvalidSessionError()
    return bearer
