"""HTTP middleware."""

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
    new_correlation_id,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id to every request and echo it back to the client."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or new_correlation_id()
        clear_request_context()
        bind_request_context(correlation_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        clear_request_context()
        return response
