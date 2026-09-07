"""Typed evidence passed from the API authorization boundary to protected services."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.tenants import AuthenticatedPrincipal
from app.authorization.permissions import PermissionId
from app.core.errors import AppError
from app.tenancy.context import TenantContext


class AuthorizationBoundaryRequiredError(AppError):
    code = "forbidden"
    status_code = 403
    message = "The requested resource is not available."


@dataclass(frozen=True, slots=True)
class AuthorizationGrant:
    """Evidence that the central service allowed one catalogued permission."""

    principal: AuthenticatedPrincipal
    tenant_context: TenantContext
    permission_id: PermissionId
