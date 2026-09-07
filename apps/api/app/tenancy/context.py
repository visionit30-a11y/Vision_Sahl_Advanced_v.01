"""Explicit tenant identity passed through service and transaction boundaries.

TenantId is a static NewType over UUID. Its version is also checked at runtime:
the platform generates UUIDv7 identities, and no request value or fallback can
manufacture a context implicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.errors import AppError
from app.models.tenant import TenantId


class InvalidTenantIdError(AppError):
    """An internal caller supplied something other than a UUIDv7 tenant identity."""

    message = "A valid tenant identity is required."


class TenantContextRequiredError(AppError):
    """A tenant-scoped operation was called without its required context."""

    message = "A trusted tenant context is required."


def validate_tenant_id(value: TenantId) -> TenantId:
    """Check the runtime identity without coercion or a default tenant."""
    if not isinstance(value, UUID) or value.version != 7:
        raise InvalidTenantIdError()
    return value


def parse_tenant_id(value: str) -> TenantId:
    """Convert text at an explicit service boundary, never from an HTTP request."""
    if not isinstance(value, str):
        raise InvalidTenantIdError()
    try:
        identity = UUID(value)
    except ValueError as exc:
        raise InvalidTenantIdError() from exc
    return validate_tenant_id(TenantId(identity))


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Immutable required context; carries identity, not authentication or status."""

    tenant_id: TenantId

    def __post_init__(self) -> None:
        validate_tenant_id(self.tenant_id)


def require_context(context: TenantContext) -> TenantContext:
    """Reject missing or malformed context before a tenant-scoped operation."""
    if not isinstance(context, TenantContext):
        raise TenantContextRequiredError()
    validate_tenant_id(context.tenant_id)
    return context
