"""Per-request context propagated to every log record.

Phase 0 binds the correlation id only. Phase 2 binds the resolved tenant id
through the same mechanism, so no logging change is required later.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog

CORRELATION_ID_HEADER = "X-Request-ID"


def new_correlation_id() -> str:
    """Generate a new correlation id."""
    return uuid4().hex


def bind_request_context(correlation_id: str, **extra: Any) -> None:
    """Bind request scoped values for the lifetime of the request."""
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id, **extra)


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current request, if any."""
    value = structlog.contextvars.get_contextvars().get("correlation_id")
    return value if isinstance(value, str) else None


def clear_request_context() -> None:
    """Clear all request scoped values."""
    structlog.contextvars.clear_contextvars()
