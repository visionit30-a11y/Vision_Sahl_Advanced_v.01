"""Unified error contract.

Every error leaves the API in the same shape and never leaks a stack trace to
the client - see SRS section 12.

    {"error": {"code": "...", "message": "...", "correlation_id": "...", "details": ...}}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_correlation_id
from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for expected, domain level errors."""

    code: str = "internal_error"
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "Unexpected error."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details
        super().__init__(self.message)


def build_error_payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    """Build the canonical error body."""
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "correlation_id": get_correlation_id(),
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


_HTTP_ERROR_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "validation_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the unified error handlers to the application."""

    @app.exception_handler(AppError)
    async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_payload(code, str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=build_error_payload(
                "validation_error",
                "The request payload is not valid.",
                details=exc.errors(),
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=type(exc).__name__,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=build_error_payload("internal_error", "Unexpected error."),
        )
