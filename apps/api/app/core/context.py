"""Separate bounded HTTP request IDs from trusted internal logging correlation."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4, uuid7

import structlog

CORRELATION_ID_HEADER = "X-Request-ID"
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}", re.ASCII)


def new_correlation_id() -> str:
    """Generate an internal identifier without incorporating request data."""
    return uuid4().hex


def safe_request_id(value: str | None) -> str:
    """Preserve the legacy echo for bounded IDs; replace malformed values."""
    return value if value is not None and _REQUEST_ID.fullmatch(value) else new_correlation_id()


def bind_request_context(correlation_id: str, **extra: Any) -> None:
    """Keep the public request ID separate from a generated logging identifier."""
    structlog.contextvars.bind_contextvars(
        **extra,
        correlation_id=safe_request_id(correlation_id),
        internal_correlation_id=uuid7(),
    )


def get_correlation_id() -> str | None:
    """Return the bounded HTTP compatibility ID, never used in audit/log emission."""
    value = structlog.contextvars.get_contextvars().get("correlation_id")
    return value if isinstance(value, str) else None


def get_internal_correlation_id() -> UUID | None:
    """Return the generated request audit/log correlation, never the client header."""
    value = structlog.contextvars.get_contextvars().get("internal_correlation_id")
    return value if type(value) is UUID and value.version == 7 else None


def clear_request_context() -> None:
    """Clear context on every success, error and cancellation path."""
    structlog.contextvars.clear_contextvars()
