"""The single fail-closed authorization decision path."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from sqlalchemy import text

from app.auth.tenants import AuthenticatedPrincipal
from app.authorization.permissions import PERMISSION_CATALOG, PermissionId
from app.db.tenant_transaction import tenant_transaction
from app.tenancy.context import TenantContext, require_context


class AuthorizationDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class _PermissionRepository(Protocol):
    async def has_permission(
        self,
        principal: AuthenticatedPrincipal,
        tenant_context: TenantContext,
        permission_id: PermissionId,
    ) -> bool: ...


class _PostgresPermissionRepository:
    """Internal live lookup; callers cannot obtain RBAC tables or a DB handle."""

    async def has_permission(
        self,
        principal: AuthenticatedPrincipal,
        tenant_context: TenantContext,
        permission_id: PermissionId,
    ) -> bool:
        async with tenant_transaction(tenant_context) as transaction:
            result = await transaction.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM auth.sessions AS session_record
                        JOIN LATERAL auth.resolve_active_membership(
                            session_record.user_id,
                            session_record.selected_membership_id,
                            session_record.selected_membership_version,
                            session_record.security_version
                        ) AS membership ON true
                        JOIN auth.membership_roles AS membership_role
                          ON membership_role.tenant_id = membership.tenant_id
                         AND membership_role.membership_id = membership.membership_id
                        JOIN auth.roles AS role_record
                          ON role_record.tenant_id = membership_role.tenant_id
                         AND role_record.id = membership_role.role_id
                         AND role_record.status = 'active'::auth.role_status
                        JOIN auth.role_permissions AS role_permission
                          ON role_permission.tenant_id = role_record.tenant_id
                         AND role_permission.role_id = role_record.id
                        WHERE session_record.id = :session_id
                          AND session_record.user_id = :user_id
                          AND session_record.selected_membership_id = :membership_id
                          AND session_record.selected_membership_version = :membership_version
                          AND session_record.revoked_at IS NULL
                          AND session_record.idle_expires_at > clock_timestamp()
                          AND session_record.absolute_expires_at > clock_timestamp()
                          AND membership.tenant_id = :tenant_id
                          AND role_permission.permission_id = :permission_id
                    )
                    """
                ),
                {
                    "session_id": principal.session_id,
                    "user_id": principal.user_id,
                    "membership_id": principal.membership_id,
                    "membership_version": principal.membership_version,
                    "tenant_id": tenant_context.tenant_id,
                    "permission_id": str(permission_id),
                },
            )
        return result is True


class AuthorizationService:
    """Return only ALLOW or DENY, and convert every dependency failure to DENY."""

    __slots__ = ("_repository",)

    def __init__(self, repository: _PermissionRepository | None = None) -> None:
        self._repository = repository or _PostgresPermissionRepository()

    async def authorize(
        self,
        principal: AuthenticatedPrincipal | None,
        tenant_context: TenantContext | None,
        permission_id: PermissionId,
    ) -> AuthorizationDecision:
        try:
            if not isinstance(principal, AuthenticatedPrincipal):
                return AuthorizationDecision.DENY
            context = require_context(tenant_context)  # type: ignore[arg-type]
            if type(permission_id) is not PermissionId or permission_id not in PERMISSION_CATALOG:
                return AuthorizationDecision.DENY
            if principal.membership_version <= 0:
                return AuthorizationDecision.DENY
            allowed = await self._repository.has_permission(principal, context, permission_id)
            return AuthorizationDecision.ALLOW if allowed else AuthorizationDecision.DENY
        # This boundary is deliberately total: a dependency defect must never become ALLOW.
        except Exception:  # noqa: BLE001
            return AuthorizationDecision.DENY
