"""Tenant-scoped role administration behind typed authorization grants."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Never

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.authorization.contracts import AuthorizationBoundaryRequiredError, AuthorizationGrant
from app.authorization.permissions import PERMISSION_CATALOG, Permission, PermissionId
from app.core.errors import AppError
from app.db.tenant_transaction import TenantTransaction, tenant_transaction
from app.models.authorization import RoleKey, new_role_id


class RoleNotFoundError(AppError):
    code = "not_found"
    status_code = 404
    message = "The requested resource was not found."


class RoleConflictError(AppError):
    code = "conflict"
    status_code = 409
    message = "The role could not be changed in its current state."


class MembershipNotFoundError(AppError):
    code = "not_found"
    status_code = 404
    message = "The requested resource was not found."


@dataclass(frozen=True, slots=True)
class RoleRecord:
    id: uuid.UUID
    tenant_id: uuid.UUID
    key: str
    display_name: str
    status: str
    version: int


def _require_grant(grant: AuthorizationGrant, permission: Permission) -> AuthorizationGrant:
    expected = PermissionId(permission.value)
    if not isinstance(grant, AuthorizationGrant) or grant.permission_id != expected:
        raise AuthorizationBoundaryRequiredError()
    return grant


def _display_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError("Role display names must contain 1-120 characters.")
    return value


class RoleAdministrationService:
    """Write RBAC state only through the existing tenant transaction and RLS boundary."""

    async def create_role(
        self, grant: AuthorizationGrant, key: RoleKey, display_name: str
    ) -> RoleRecord:
        grant = _require_grant(grant, Permission.TENANT_ROLES_MANAGE)
        role_id = new_role_id()
        try:
            async with tenant_transaction(grant.tenant_context) as transaction:
                row = (
                    await transaction.execute(
                        text(
                            "INSERT INTO auth.roles(id,tenant_id,key,display_name) "
                            "VALUES (:id,:tenant_id,:key,:display_name) "
                            "RETURNING id,tenant_id,key,display_name,status,version"
                        ),
                        {
                            "id": role_id,
                            "tenant_id": grant.tenant_context.tenant_id,
                            "key": str(key),
                            "display_name": _display_name(display_name),
                        },
                    )
                ).one()
        except IntegrityError as exc:
            raise RoleConflictError() from exc
        return RoleRecord(*row._tuple())

    async def update_role(
        self,
        grant: AuthorizationGrant,
        role_id: uuid.UUID,
        *,
        expected_version: int,
        display_name: str,
    ) -> RoleRecord:
        grant = _require_grant(grant, Permission.TENANT_ROLES_MANAGE)
        async with tenant_transaction(grant.tenant_context) as transaction:
            row = (
                await transaction.execute(
                    text(
                        "UPDATE auth.roles SET display_name=:display_name,"
                        "version=version+1,updated_at=clock_timestamp() "
                        "WHERE id=:role_id AND version=:expected_version "
                        "RETURNING id,tenant_id,key,display_name,status,version"
                    ),
                    {
                        "role_id": role_id,
                        "expected_version": expected_version,
                        "display_name": _display_name(display_name),
                    },
                )
            ).one_or_none()
            if row is None:
                await self._raise_missing_or_stale(transaction, role_id)
        return RoleRecord(*row._tuple())

    async def disable_role(
        self, grant: AuthorizationGrant, role_id: uuid.UUID, *, expected_version: int
    ) -> RoleRecord:
        grant = _require_grant(grant, Permission.TENANT_ROLES_MANAGE)
        async with tenant_transaction(grant.tenant_context) as transaction:
            row = (
                await transaction.execute(
                    text(
                        "UPDATE auth.roles SET status='inactive',version=version+1,"
                        "updated_at=clock_timestamp() "
                        "WHERE id=:role_id AND version=:expected_version AND status='active' "
                        "RETURNING id,tenant_id,key,display_name,status,version"
                    ),
                    {"role_id": role_id, "expected_version": expected_version},
                )
            ).one_or_none()
            if row is None:
                await self._raise_missing_or_stale(transaction, role_id)
        return RoleRecord(*row._tuple())

    async def assign_permission(
        self, grant: AuthorizationGrant, role_id: uuid.UUID, permission: Permission
    ) -> bool:
        grant = _require_grant(grant, Permission.TENANT_ROLES_MANAGE)
        permission_id = self._tenant_permission(permission)
        async with tenant_transaction(grant.tenant_context) as transaction:
            await self._require_active_role(transaction, role_id)
            result = await transaction.execute(
                text(
                    "INSERT INTO auth.role_permissions(tenant_id,role_id,permission_id) "
                    "VALUES (:tenant_id,:role_id,:permission_id) "
                    "ON CONFLICT DO NOTHING RETURNING 1"
                ),
                {
                    "tenant_id": grant.tenant_context.tenant_id,
                    "role_id": role_id,
                    "permission_id": permission_id,
                },
            )
        return result.scalar_one_or_none() == 1

    async def remove_permission(
        self, grant: AuthorizationGrant, role_id: uuid.UUID, permission: Permission
    ) -> bool:
        grant = _require_grant(grant, Permission.TENANT_ROLES_MANAGE)
        permission_id = self._tenant_permission(permission)
        async with tenant_transaction(grant.tenant_context) as transaction:
            await self._require_role(transaction, role_id)
            result = await transaction.execute(
                text(
                    "DELETE FROM auth.role_permissions "
                    "WHERE role_id=:role_id AND permission_id=:permission_id RETURNING 1"
                ),
                {"role_id": role_id, "permission_id": permission_id},
            )
        return result.scalar_one_or_none() == 1

    async def assign_role(
        self, grant: AuthorizationGrant, membership_id: uuid.UUID, role_id: uuid.UUID
    ) -> bool:
        grant = _require_grant(grant, Permission.TENANT_MEMBERSHIPS_MANAGE)
        async with tenant_transaction(grant.tenant_context) as transaction:
            await self._require_active_role(transaction, role_id)
            active = await transaction.scalar(
                text("SELECT auth.is_active_membership_in_tenant(:membership,:tenant)"),
                {
                    "membership": membership_id,
                    "tenant": grant.tenant_context.tenant_id,
                },
            )
            if active is not True:
                raise MembershipNotFoundError()
            result = await transaction.execute(
                text(
                    "INSERT INTO auth.membership_roles(tenant_id,membership_id,role_id) "
                    "VALUES (:tenant_id,:membership_id,:role_id) "
                    "ON CONFLICT DO NOTHING RETURNING 1"
                ),
                {
                    "tenant_id": grant.tenant_context.tenant_id,
                    "membership_id": membership_id,
                    "role_id": role_id,
                },
            )
        return result.scalar_one_or_none() == 1

    async def remove_role(
        self, grant: AuthorizationGrant, membership_id: uuid.UUID, role_id: uuid.UUID
    ) -> bool:
        grant = _require_grant(grant, Permission.TENANT_MEMBERSHIPS_MANAGE)
        async with tenant_transaction(grant.tenant_context) as transaction:
            await self._require_role(transaction, role_id)
            active = await transaction.scalar(
                text("SELECT auth.is_active_membership_in_tenant(:membership,:tenant)"),
                {
                    "membership": membership_id,
                    "tenant": grant.tenant_context.tenant_id,
                },
            )
            if active is not True:
                raise MembershipNotFoundError()
            result = await transaction.execute(
                text(
                    "DELETE FROM auth.membership_roles "
                    "WHERE membership_id=:membership_id AND role_id=:role_id RETURNING 1"
                ),
                {"membership_id": membership_id, "role_id": role_id},
            )
        return result.scalar_one_or_none() == 1

    @staticmethod
    def _tenant_permission(permission: Permission) -> PermissionId:
        if type(permission) is not Permission:
            raise AuthorizationBoundaryRequiredError()
        permission_id = PermissionId(permission.value)
        if permission_id not in PERMISSION_CATALOG or not permission_id.startswith("tenant."):
            raise AuthorizationBoundaryRequiredError()
        return permission_id

    @staticmethod
    async def _require_role(transaction: TenantTransaction, role_id: uuid.UUID) -> str:
        status = await transaction.scalar(
            text("SELECT status::text FROM auth.roles WHERE id=:role_id"),
            {"role_id": role_id},
        )
        if not isinstance(status, str):
            raise RoleNotFoundError()
        return status

    async def _require_active_role(
        self, transaction: TenantTransaction, role_id: uuid.UUID
    ) -> None:
        if await self._require_role(transaction, role_id) != "active":
            raise RoleConflictError()

    @staticmethod
    async def _raise_missing_or_stale(transaction: TenantTransaction, role_id: uuid.UUID) -> Never:
        exists = await transaction.scalar(
            text("SELECT EXISTS(SELECT 1 FROM auth.roles WHERE id=:role_id)"),
            {"role_id": role_id},
        )
        if exists is not True:
            raise RoleNotFoundError()
        raise RoleConflictError()


role_administration_service = RoleAdministrationService()
