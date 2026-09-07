"""Resolver contract and the fail-closed HTTP default for Phase 2A."""

from __future__ import annotations

from typing import Protocol

from app.core.logging import get_logger
from app.tenancy.context import TenantContext, TenantContextRequiredError

logger = get_logger(__name__)


class TenantResolver(Protocol):
    """Supply context from a source appropriate to the calling boundary."""

    def resolve(self) -> TenantContext:
        """Return a required context or raise; an optional result is never valid."""
        ...


class NoTenantResolver:
    """HTTP has no trusted identity source in Phase 2A, so resolution always fails.

    There is deliberately no request argument: bodies, queries, headers and
    hostnames cannot establish tenant context.
    """

    def resolve(self) -> TenantContext:
        logger.error("tenant_context_missing")
        raise TenantContextRequiredError()
