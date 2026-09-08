"""Closed final emission policy for structlog, stdlib and server diagnostics.

Key masking remains defense in depth. Only declared diagnostic events and safe
scalar fields reach a renderer; exception text, SQL, arguments and request data
never do. Durable security events are written through the separate audit boundary.
"""

from __future__ import annotations

import logging
import math
import re
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog

from app.core.context import get_internal_correlation_id

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "bearer",
        "session_bearer",
        "state_token",
        "csrf",
        "x-csrf-token",
        "session_token",
        "reset_token",
        "csrf_token",
        "cookie",
        "set-cookie",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "apikey",
        "private_key",
        "national_id",
        "email",
        "normalized_email",
        "ip",
        "ip_address",
        "subject_key",
        "iban",
        "bank_account",
        "database_url",
        "migration_database_url",
        "redis_url",
        "auth_hmac_key",
        "db_credentials",
    }
)
MASK = "***"
_DIAGNOSTIC_EVENTS = frozenset(
    {
        "application_started",
        "application_stopped",
        "request_completed",
        "unhandled_exception",
        "tenant_context_missing",
        "audit_write_failed",
    }
)
_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})
_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})
_VERSION = re.compile(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}", re.ASCII)
_ROUTE_TEMPLATES: frozenset[str] = frozenset()
_ORIGINAL_RECORD_FACTORY = logging.getLogRecordFactory()


def _redact_sensitive(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Legacy recursive masking; the closed projection below is the emission gate."""

    def redact(value: Any) -> Any:
        if isinstance(value, MutableMapping):
            return {
                key: MASK if str(key).lower() in SENSITIVE_KEYS else redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(redact(item) for item in value)
        return value

    return redact(event_dict)


def _internal_correlation() -> str | None:
    value = get_internal_correlation_id()
    return str(value) if value is not None else None


def _safe_log_projection(
    _logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    """Project before rendering, never format unknown values or exception objects."""
    supplied_event = event_dict.get("event")
    event = supplied_event if type(supplied_event) is str else "diagnostic_event"
    safe: dict[str, Any] = {
        "event": event if event in _DIAGNOSTIC_EVENTS else "diagnostic_event",
        "level": method_name if method_name in _LEVELS else "info",
    }
    correlation = _internal_correlation()
    if correlation is not None:
        safe["correlation_id"] = correlation
    if safe["event"] == "request_completed":
        method = event_dict.get("method")
        safe["method"] = method if type(method) is str and method in _METHODS else "OTHER"
        route = event_dict.get("route")
        safe["route"] = route if type(route) is str and route in _ROUTE_TEMPLATES else "unmatched"
        duration = cast(int | float, event_dict.get("duration_ms"))
        if (
            type(duration) in (int, float)
            and math.isfinite(duration)
            and 0 <= duration < 86_400_000
        ):
            safe["duration_ms"] = round(duration, 2)
    elif safe["event"] == "application_started":
        environment = event_dict.get("environment")
        if type(environment) is str and environment in {
            "development",
            "test",
            "staging",
            "production",
        }:
            safe["environment"] = environment
        version = event_dict.get("version")
        if type(version) is str and _VERSION.fullmatch(version):
            safe["version"] = version
        if type(event_dict.get("redis_enabled")) is bool:
            safe["redis_enabled"] = event_dict["redis_enabled"]
    elif safe["event"] == "unhandled_exception":
        category = event_dict.get("error_category")
        safe["error_category"] = "database" if category == "database" else "unexpected"
    return safe


def _safe_record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """Sanitize before any stdlib/Uvicorn handler can format args or a traceback."""
    record = _ORIGINAL_RECORD_FACTORY(*args, **kwargs)
    component = record.name.split(".", 1)[0]
    if component not in {"uvicorn", "sqlalchemy", "httpx", "httpcore", "asyncio", "app"}:
        component = "other"
    safe: dict[str, Any] = {"event": "stdlib_diagnostic", "component": component}
    level = record.levelname.lower()
    safe["level"] = level if level in _LEVELS else "info"
    correlation = _internal_correlation()
    if correlation is not None:
        safe["correlation_id"] = correlation
    record.msg = structlog.processors.JSONRenderer()(None, "info", safe)
    record.args = ()
    record.exc_info = None
    record.exc_text = None
    record.stack_info = None
    return record


def configure_logging(level: str = "INFO", log_format: str = "console") -> None:
    """Install the same fail-closed emission policy for all application log paths."""
    # Import after the application router is composed; no request supplies this list.
    from fastapi.routing import iter_route_contexts

    from app.api.router import api_router

    global _ROUTE_TEMPLATES
    _ROUTE_TEMPLATES = frozenset(
        path
        for route in iter_route_contexts(api_router.routes)
        if isinstance(path := route.path, str)
    )
    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            _safe_log_projection,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    logging.setLogRecordFactory(_safe_record_factory)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level, force=True)
    # Uvicorn installs handlers before importing the app. They must not reformat
    # exceptions after our projection or preserve an access log's raw URL/client.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").setLevel(max(numeric_level, logging.WARNING))
    logging.getLogger("sqlalchemy.engine").setLevel(max(numeric_level, logging.WARNING))


def get_logger(name: str | None = None) -> Any:
    """Return a logger governed by the final closed projection."""
    return structlog.get_logger(name)
