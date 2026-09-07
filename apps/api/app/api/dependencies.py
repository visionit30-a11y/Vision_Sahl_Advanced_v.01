"""Tenant-scoped API dependencies, with no request-derived identity in Phase 2A."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.auth.tenants import TrustedTenantAccess
from app.tenancy.context import TenantContext, require_context
from app.tenancy.resolution import NoTenantResolver, TenantResolver


def get_tenant_resolver() -> TenantResolver:
    """The production HTTP default has no trusted tenant identity source yet."""
    return NoTenantResolver()


def require_tenant_context(
    resolver: Annotated[TenantResolver, Depends(get_tenant_resolver)],
) -> TenantContext:
    """Reject requests before entering any service that requires tenant context."""
    return require_context(resolver.resolve())


def tenant_context_from_authenticated_access(access: TrustedTenantAccess) -> TenantContext:
    """Accept only the result of the trusted auth resolver; request selectors are not inputs."""
    return require_context(access.context)
