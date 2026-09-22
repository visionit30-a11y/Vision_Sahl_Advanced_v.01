"""Tenant user administration behind typed authorization grants and trusted context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.authorization.contracts import AuthorizationBoundaryRequiredError, AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.core.errors import AppError
from app.db.tenant_transaction import tenant_transaction
from app.models.identity import new_membership_id, new_user_id, normalize_email


class TenantUserNotFoundError(AppError):
    code = "not_found"
    status_code = 404
    message = "The requested resource was not found."


class TenantUserConflictError(AppError):
    code = "conflict"
    status_code = 409
    message = "The request conflicts with the current state."


class TenantUserChangeDeniedError(AppError):
    code = "forbidden"
    status_code = 403
    message = "The requested resource is not available."


@dataclass(frozen=True, slots=True)
class TenantUserRecord:
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    user_status: str
    membership_status: str
    membership_version: int
    joined_at: datetime | None
    left_at: datetime | None
    role_ids: tuple[uuid.UUID, ...]
    role_keys: tuple[str, ...]
    role_titles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TenantRoleRecord:
    role_id: uuid.UUID
    role_key: str
    display_name: str
    status: str
    kind: str
    version: int
    permissions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TenantAccessEventRecord:
    id: uuid.UUID
    event_type: str
    actor_membership_id: uuid.UUID | None
    target_membership_id: uuid.UUID
    role_id: uuid.UUID | None
    created_at: datetime


def _require(grant: AuthorizationGrant, permission: Permission) -> AuthorizationGrant:
    expected = PermissionId(permission.value)
    if not isinstance(grant, AuthorizationGrant) or grant.permission_id != expected:
        raise AuthorizationBoundaryRequiredError()
    return grant


def _translate_database_error(error: DBAPIError) -> AppError:
    code = getattr(error.orig, "sqlstate", None)
    message = getattr(getattr(error.orig, "diag", None), "message_primary", "")
    if code == "P0002":
        return TenantUserNotFoundError()
    if code in {"23514", "40001"} or message in {"last_tenant_admin", "membership_conflict"}:
        return TenantUserConflictError()
    if code == "42501":
        return TenantUserChangeDeniedError()
    return TenantUserConflictError()


class TenantAdministrationService:
    async def list_users(self, grant: AuthorizationGrant) -> list[TenantUserRecord]:
        grant = _require(grant, Permission.TENANT_USERS_READ)
        async with tenant_transaction(grant.tenant_context) as transaction:
            rows = (
                await transaction.execute(text("SELECT * FROM auth.tenant_user_directory()"))
            ).all()
        return [
            TenantUserRecord(
                row.membership_id,
                row.user_id,
                row.email,
                row.user_status,
                row.membership_status,
                row.membership_version,
                row.joined_at,
                row.left_at,
                tuple(row.role_ids or ()),
                tuple(row.role_keys or ()),
                tuple(row.role_titles or ()),
            )
            for row in rows
        ]

    async def list_roles(self, grant: AuthorizationGrant) -> list[TenantRoleRecord]:
        grant = _require(grant, Permission.TENANT_ROLES_READ)
        async with tenant_transaction(grant.tenant_context) as transaction:
            rows = (
                await transaction.execute(text("SELECT * FROM auth.tenant_role_directory()"))
            ).all()
        return [
            TenantRoleRecord(
                row.role_id,
                row.role_key,
                row.display_name,
                row.status,
                row.kind,
                row.version,
                tuple(row.permissions or ()),
            )
            for row in rows
        ]

    async def invite(self, grant: AuthorizationGrant, email: str) -> uuid.UUID:
        grant = _require(grant, Permission.TENANT_USERS_INVITE)
        normalized = normalize_email(email)
        user_id = uuid.UUID(str(new_user_id()))
        membership_id = uuid.UUID(str(new_membership_id()))
        try:
            async with tenant_transaction(grant.tenant_context) as transaction:
                row = (
                    await transaction.execute(
                        text(
                            "SELECT * FROM auth.invite_tenant_user("
                            ":email,:normalized,:user,:membership,:actor)"
                        ),
                        {
                            "email": email,
                            "normalized": normalized,
                            "user": user_id,
                            "membership": membership_id,
                            "actor": grant.principal.membership_id,
                        },
                    )
                ).one()
        except (DBAPIError, IntegrityError) as error:
            raise _translate_database_error(error) from None
        return row.membership_id

    async def set_membership_status(
        self,
        grant: AuthorizationGrant,
        membership_id: uuid.UUID,
        *,
        status: str,
        expected_version: int,
    ) -> tuple[str, int]:
        grant = _require(grant, Permission.TENANT_USERS_MANAGE)
        try:
            async with tenant_transaction(grant.tenant_context) as transaction:
                row = (
                    await transaction.execute(
                        text(
                            "SELECT * FROM auth.set_tenant_membership_status("
                            ":membership,:status,:expected,:actor)"
                        ),
                        {
                            "membership": membership_id,
                            "status": status,
                            "expected": expected_version,
                            "actor": grant.principal.membership_id,
                        },
                    )
                ).one()
        except (DBAPIError, IntegrityError) as error:
            raise _translate_database_error(error) from None
        return row.membership_status, row.membership_version

    async def access_history(
        self, grant: AuthorizationGrant, *, limit: int = 100
    ) -> list[TenantAccessEventRecord]:
        grant = _require(grant, Permission.TENANT_ACCESS_AUDIT_READ)
        async with tenant_transaction(grant.tenant_context) as transaction:
            rows = (
                await transaction.execute(
                    text(
                        "SELECT id,event_type,actor_membership_id,target_membership_id,"
                        "role_id,created_at FROM app.tenant_access_events "
                        "ORDER BY created_at DESC,id DESC LIMIT :limit"
                    ),
                    {"limit": limit},
                )
            ).all()
        return [TenantAccessEventRecord(*row._tuple()) for row in rows]


tenant_administration_service = TenantAdministrationService()
