"""HTTP correlation and no-store middleware without raw request logging."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import (
    CORRELATION_ID_HEADER,
    bind_request_context,
    clear_request_context,
    get_internal_correlation_id,
    safe_request_id,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def request_route_template(request: Request) -> str:
    """A registered route template contains no client path or query values."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) else "unmatched"


class UiSettingsNoStoreMiddleware(BaseHTTPMiddleware):
    """Prevent caching of settings and authentication responses, including errors."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if request.url.path.split("/")[1] in {"ui-settings", "auth"}:
            response.headers["Cache-Control"] = "no-store"
        return response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Echo a bounded legacy request ID while logs use an independent internal ID."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = safe_request_id(request.headers.get(CORRELATION_ID_HEADER))
        # Outer exception handlers cannot rely on an inner middleware's contextvar.
        request.state.response_correlation_id = correlation_id
        clear_request_context()
        bind_request_context(correlation_id)
        request.state.internal_correlation_id = get_internal_correlation_id()
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            return response
        finally:
            try:
                logger.info(
                    "request_completed",
                    method=request.method,
                    route=request_route_template(request),
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            finally:
                clear_request_context()
