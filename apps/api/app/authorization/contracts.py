"""Typed evidence passed from the API authorization boundary to protected services."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.tenants import AuthenticatedPrincipal
from app.authorization.permissions import PermissionId
from app.tenancy.context import TenantContext


@dataclass(frozen=True, slots=True)
class AuthorizationGrant:
    """Evidence that the central service allowed one catalogued permission."""

    principal: AuthenticatedPrincipal
    tenant_context: TenantContext
    permission_id: PermissionId
