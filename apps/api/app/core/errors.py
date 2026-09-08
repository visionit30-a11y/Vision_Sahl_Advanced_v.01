"""Unified public errors projected from a closed, non-sensitive message catalog."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import CORRELATION_ID_HEADER, get_correlation_id
from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Expected domain failure; public emission never trusts instance overrides."""

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
        requested_code = code or self.code
        self.code = requested_code if requested_code in _PUBLIC_MESSAGES else "internal_error"
        messages = _PUBLIC_MESSAGES[self.code]
        requested_message = message or self.message
        self.message = requested_message if requested_message in messages else messages[0]
        self.status_code = status_code or self.status_code
        self.details = None
        super().__init__(self.message)


# Preserve approved messages/codes while rejecting arbitrary exception/driver text.
_PUBLIC_MESSAGES: dict[str, tuple[str, ...]] = {
    "internal_error": (
        "Unexpected error.",
        "A trusted tenant context is required.",
        "A valid tenant identity is required.",
    ),
    "bad_request": ("The request could not be completed.",),
    "unauthorized": ("Authentication is required.",),
    "invalid_session": ("Authentication is required.",),
    "forbidden": ("The requested resource is not available.",),
    "not_found": (
        "The requested resource was not found.",
        "The requested UI settings layer was not found.",
    ),
    "method_not_allowed": ("The request method is not allowed.",),
    "conflict": (
        "The request conflicts with the current state.",
        "The role could not be changed in its current state.",
        "UI settings changed; reload them before retrying.",
    ),
    "validation_error": ("The request payload is not valid.",),
    "service_unavailable": ("The service is temporarily unavailable.",),
    "http_error": ("The request could not be completed.",),
    "csrf_rejected": ("The request could not be verified.",),
    "tenant_context_changed": ("The trusted tenant context changed.",),
    "tenant_access_denied": ("The requested tenant context is not available.",),
    "throttled": ("The request could not be completed. Try again later.",),
}
_VALIDATION_TYPES = frozenset(
    {
        "missing",
        "extra_forbidden",
        "json_invalid",
        "value_error",
        "assertion_error",
        "string_type",
        "string_too_short",
        "string_too_long",
        "string_pattern_mismatch",
        "int_type",
        "int_parsing",
        "int_from_float",
        "float_type",
        "float_parsing",
        "bool_type",
        "bool_parsing",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "uuid_type",
        "uuid_parsing",
        "uuid_version",
        "enum",
        "literal_error",
        "dict_type",
        "list_type",
        "model_type",
        "model_attributes_type",
        "finite_number",
        "recursion_loop",
        "invalid_value",
    }
)


def _known_validation_location(error: dict[str, Any], request: Request | None) -> list[str]:
    """Expose only the source and one statically declared schema field.

    Deeper dict keys, array indexes, union tags and validator-defined loc values
    may be derived from input. Omitting them avoids a second data disclosure path.
    """
    loc = error.get("loc")
    if not isinstance(loc, (list, tuple)) or not loc:
        return []
    source = loc[0]
    if type(source) is not str or source not in {"body", "query", "path", "header", "cookie"}:
        return []
    safe = [source]
    if request is None or len(loc) < 2 or type(loc[1]) is not str:
        return safe
    dependant = getattr(request.scope.get("route"), "dependant", None)
    fields = getattr(dependant, f"{source}_params", [])
    names = {field.alias for field in fields if isinstance(field.alias, str)}
    if source == "body" and len(fields) == 1:
        annotation = fields[0].field_info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            names = {field.alias or name for name, field in annotation.model_fields.items()}
    if loc[1] in names:
        safe.append(loc[1])
    return safe


def _safe_error_details(value: Any, *, request: Request | None = None) -> Any:
    """Discard arbitrary details, including unknown field names and nested secrets."""
    if not isinstance(value, (list, tuple)):
        return None
    safe: list[dict[str, Any]] = []
    for error in value[:20]:
        if type(error) is not dict:
            continue
        supplied_type = error.get("type")
        kind = supplied_type if type(supplied_type) is str else "invalid_value"
        safe.append(
            {
                "type": kind if kind in _VALIDATION_TYPES else "invalid_value",
                "loc": _known_validation_location(error, request),
            }
        )
    return safe


def build_error_payload(
    code: str,
    message: str,
    details: Any = None,
    *,
    request: Request | None = None,
) -> dict[str, Any]:
    """Build the established envelope using only catalogued message/code pairs."""
    if type(code) is not str or code not in _PUBLIC_MESSAGES:
        code = "internal_error"
    messages = _PUBLIC_MESSAGES[code]
    public_message = message if type(message) is str and message in messages else messages[0]
    correlation_id = get_correlation_id()
    if request is not None:
        correlation_id = getattr(request.state, "response_correlation_id", correlation_id)
    error: dict[str, Any] = {
        "code": code,
        "message": public_message,
        "correlation_id": correlation_id,
    }
    if code == "validation_error" and details is not None:
        error["details"] = _safe_error_details(details, request=request)
    return {"error": error}


_HTTP_ERROR_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach closed error handlers without formatting exception values."""

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        # Class declarations are stable; an instance's message/details may carry input.
        contract = type(exc)
        return JSONResponse(
            status_code=contract.status_code,
            content=build_error_payload(contract.code, contract.message, request=request),
            headers={"X-Auth-Error": "tenant_context_changed"}
            if contract.code == "tenant_context_changed"
            else None,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_payload(code, _PUBLIC_MESSAGES[code][0], request=request),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=build_error_payload(
                "validation_error",
                "The request payload is not valid.",
                details=exc.errors(),
                request=request,
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # The outer Starlette handler runs after the inner middleware cleans up.
        # Rebind only its generated UUID for this one diagnostic, then restore.
        with structlog.contextvars.bound_contextvars(
            internal_correlation_id=getattr(request.state, "internal_correlation_id", None)
        ):
            logger.error(
                "unhandled_exception",
                error_category="database" if isinstance(exc, SQLAlchemyError) else "unexpected",
            )
        headers: dict[str, str] = {}
        correlation = getattr(request.state, "response_correlation_id", None)
        if correlation is not None:
            headers[CORRELATION_ID_HEADER] = correlation
        if request.url.path.split("/")[1] in {"auth", "ui-settings"}:
            headers["Cache-Control"] = "no-store"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=build_error_payload("internal_error", "Unexpected error.", request=request),
            headers=headers,
        )
