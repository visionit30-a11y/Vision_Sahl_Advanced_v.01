"""Tenant-scoped role administration behind typed authorization grants."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Never

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.audit.contracts import SecurityAuditEvent, SecurityEventResult, SecurityEventType
from app.audit.writer import SecurityEventWriter
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
    kind: str
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
                event = self._event(grant, SecurityEventType.ROLE_CREATED, role_id)
                writer = SecurityEventWriter(transaction)
                await writer.prepare_role(event, grant.principal.membership_version)
                row = (
                    await transaction.execute(
                        text(
                            "INSERT INTO auth.roles(id,tenant_id,key,display_name) "
                            "VALUES (:id,:tenant_id,:key,:display_name) "
                            "RETURNING id,tenant_id,key,display_name,status,kind,version"
                        ),
                        {
                            "id": role_id,
                            "tenant_id": grant.tenant_context.tenant_id,
                            "key": str(key),
                            "display_name": _display_name(display_name),
                        },
                    )
                ).one()
                await writer.write(event)
                await self._write_access_event(
                    transaction, grant, grant.principal.membership_id, role_id, "role_created"
                )
        except IntegrityError:
            raise RoleConflictError() from None
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
            await self._require_custom_role(transaction, role_id)
            event = self._event(grant, SecurityEventType.ROLE_UPDATED, role_id)
            writer = SecurityEventWriter(transaction)
            await writer.prepare_role(event, grant.principal.membership_version)
            row = (
                await transaction.execute(
                    text(
                        "UPDATE auth.roles SET display_name=:display_name,"
                        "version=version+1,updated_at=clock_timestamp() "
                        "WHERE id=:role_id AND version=:expected_version "
                        "RETURNING id,tenant_id,key,display_name,status,kind,version"
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
            await writer.write(event)
            await self._write_access_event(
                transaction, grant, grant.principal.membership_id, role_id, "role_updated"
            )
        return RoleRecord(*row._tuple())

    async def disable_role(
        self, grant: AuthorizationGrant, role_id: uuid.UUID, *, expected_version: int
    ) -> RoleRecord:
        grant = _require_grant(grant, Permission.TENANT_ROLES_MANAGE)
        async with tenant_transaction(grant.tenant_context) as transaction:
            await self._require_custom_role(transaction, role_id)
            event = self._event(grant, SecurityEventType.ROLE_DISABLED, role_id)
            writer = SecurityEventWriter(transaction)
            await writer.prepare_role(event, grant.principal.membership_version)
            row = (
                await transaction.execute(
                    text(
                        "UPDATE auth.roles SET status='inactive',version=version+1,"
                        "updated_at=clock_timestamp() "
                        "WHERE id=:role_id AND version=:expected_version AND status='active' "
                        "RETURNING id,tenant_id,key,display_name,status,kind,version"
                    ),
                    {"role_id": role_id, "expected_version": expected_version},
                )
            ).one_or_none()
            if row is None:
                await self._raise_missing_or_stale(transaction, role_id)
            await writer.write(event)
            await self._write_access_event(
                transaction, grant, grant.principal.membership_id, role_id, "role_disabled"
            )
        return RoleRecord(*row._tuple())

    async def assign_permission(
        self, grant: AuthorizationGrant, role_id: uuid.UUID, permission: Permission
    ) -> bool:
        grant = _require_grant(grant, Permission.TENANT_ROLES_MANAGE)
        permission_id = self._tenant_permission(permission)
        async with tenant_transaction(grant.tenant_context) as transaction:
            await self._require_custom_role(transaction, role_id)
            await self._require_actor_permission(transaction, grant, permission_id)
            await self._require_active_role(transaction, role_id)
            event = self._event(
                grant,
                SecurityEventType.ROLE_PERMISSION_ASSIGNED,
                role_id,
                permission_id=permission_id,
            )
            writer = SecurityEventWriter(transaction)
            await writer.prepare_role(event, grant.principal.membership_version)
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
            changed = result.scalar_one_or_none() == 1
            if changed:
                await writer.write(event)
                await self._write_access_event(
                    transaction,
                    grant,
                    grant.principal.membership_id,
                    role_id,
                    "permission_assigned",
                )
            else:
                await writer.cancel_role(event)
        return changed

    async def remove_permission(
        self, grant: AuthorizationGrant, role_id: uuid.UUID, permission: Permission
    ) -> bool:
        grant = _require_grant(grant, Permission.TENANT_ROLES_MANAGE)
        permission_id = self._tenant_permission(permission)
        async with tenant_transaction(grant.tenant_context) as transaction:
            await self._require_custom_role(transaction, role_id)
            await self._require_role(transaction, role_id)
            event = self._event(
                grant,
                SecurityEventType.ROLE_PERMISSION_REMOVED,
                role_id,
                permission_id=permission_id,
            )
            writer = SecurityEventWriter(transaction)
            await writer.prepare_role(event, grant.principal.membership_version)
            result = await transaction.execute(
                text(
                    "DELETE FROM auth.role_permissions "
                    "WHERE role_id=:role_id AND permission_id=:permission_id RETURNING 1"
                ),
                {"role_id": role_id, "permission_id": permission_id},
            )
            changed = result.scalar_one_or_none() == 1
            if changed:
                await writer.write(event)
                await self._write_access_event(
                    transaction,
                    grant,
                    grant.principal.membership_id,
                    role_id,
                    "permission_removed",
                )
            else:
                await writer.cancel_role(event)
        return changed

    async def assign_role(
        self, grant: AuthorizationGrant, membership_id: uuid.UUID, role_id: uuid.UUID
    ) -> bool:
        grant = _require_grant(grant, Permission.TENANT_MEMBERSHIPS_MANAGE)
        async with tenant_transaction(grant.tenant_context) as transaction:
            _, kind = await self._role_state(transaction, role_id)
            if membership_id == grant.principal.membership_id:
                raise RoleConflictError()
            if kind == "tenant_admin":
                await self._require_actor_tenant_admin(transaction, grant)
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
            event = self._event(
                grant,
                SecurityEventType.MEMBERSHIP_ROLE_ASSIGNED,
                role_id,
                target_membership_id=membership_id,
            )
            writer = SecurityEventWriter(transaction)
            await writer.prepare_role(event, grant.principal.membership_version)
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
            changed = result.scalar_one_or_none() == 1
            if changed:
                await writer.write(event)
                await self._write_access_event(
                    transaction, grant, membership_id, role_id, "role_assigned"
                )
            else:
                await writer.cancel_role(event)
        return changed

    async def remove_role(
        self, grant: AuthorizationGrant, membership_id: uuid.UUID, role_id: uuid.UUID
    ) -> bool:
        grant = _require_grant(grant, Permission.TENANT_MEMBERSHIPS_MANAGE)
        async with tenant_transaction(grant.tenant_context) as transaction:
            _, kind = await self._role_state(transaction, role_id)
            if membership_id == grant.principal.membership_id:
                raise RoleConflictError()
            if kind == "tenant_admin":
                if membership_id == grant.principal.membership_id:
                    raise RoleConflictError()
                other_admins = await transaction.scalar(
                    text(
                        "SELECT count(*) FROM auth.membership_roles mr "
                        "JOIN auth.tenant_memberships m ON m.tenant_id=mr.tenant_id "
                        "AND m.id=mr.membership_id WHERE mr.role_id=:role_id "
                        "AND mr.membership_id<>:membership AND m.status='active'"
                    ),
                    {"role_id": role_id, "membership": membership_id},
                )
                if not isinstance(other_admins, int) or other_admins < 1:
                    raise RoleConflictError()
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
            event = self._event(
                grant,
                SecurityEventType.MEMBERSHIP_ROLE_REMOVED,
                role_id,
                target_membership_id=membership_id,
            )
            writer = SecurityEventWriter(transaction)
            await writer.prepare_role(event, grant.principal.membership_version)
            result = await transaction.execute(
                text(
                    "DELETE FROM auth.membership_roles "
                    "WHERE membership_id=:membership_id AND role_id=:role_id RETURNING 1"
                ),
                {"membership_id": membership_id, "role_id": role_id},
            )
            changed = result.scalar_one_or_none() == 1
            if changed:
                await writer.write(event)
                await self._write_access_event(
                    transaction, grant, membership_id, role_id, "role_removed"
                )
            else:
                await writer.cancel_role(event)
        return changed

    @staticmethod
    async def _write_access_event(
        transaction: TenantTransaction,
        grant: AuthorizationGrant,
        target_membership_id: uuid.UUID,
        role_id: uuid.UUID,
        event_type: str,
    ) -> None:
        await transaction.execute(
            text(
                "INSERT INTO app.tenant_access_events("
                "id,tenant_id,actor_membership_id,target_membership_id,role_id,event_type) "
                "VALUES (:id,:tenant,:actor,:target,:role,:event_type)"
            ),
            {
                "id": uuid.uuid7(),
                "tenant": grant.tenant_context.tenant_id,
                "actor": grant.principal.membership_id,
                "target": target_membership_id,
                "role": role_id,
                "event_type": event_type,
            },
        )

    @staticmethod
    def _event(
        grant: AuthorizationGrant,
        event_type: SecurityEventType,
        role_id: uuid.UUID,
        *,
        permission_id: PermissionId | None = None,
        target_membership_id: uuid.UUID | None = None,
    ) -> SecurityAuditEvent:
        return SecurityAuditEvent(
            event_type=event_type,
            result=SecurityEventResult.SUCCESS,
            user_id=grant.principal.user_id,
            session_id=grant.principal.session_id,
            membership_id=grant.principal.membership_id,
            role_id=role_id,
            permission_id=permission_id,
            target_membership_id=target_membership_id,
        )

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
        status, _ = await self._role_state(transaction, role_id)
        if status != "active":
            raise RoleConflictError()

    @staticmethod
    async def _role_state(transaction: TenantTransaction, role_id: uuid.UUID) -> tuple[str, str]:
        row = (
            await transaction.execute(
                text("SELECT status::text,kind::text FROM auth.roles WHERE id=:role_id"),
                {"role_id": role_id},
            )
        ).one_or_none()
        if row is None:
            raise RoleNotFoundError()
        return row.status, row.kind

    async def _require_custom_role(
        self, transaction: TenantTransaction, role_id: uuid.UUID
    ) -> None:
        _, kind = await self._role_state(transaction, role_id)
        if kind != "custom":
            raise RoleConflictError()

    @staticmethod
    async def _require_actor_permission(
        transaction: TenantTransaction,
        grant: AuthorizationGrant,
        permission_id: PermissionId,
    ) -> None:
        allowed = await transaction.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM auth.membership_roles mr "
                "JOIN auth.roles r ON r.tenant_id=mr.tenant_id AND r.id=mr.role_id "
                "JOIN auth.role_permissions rp ON rp.tenant_id=r.tenant_id AND rp.role_id=r.id "
                "WHERE mr.membership_id=:membership AND r.status='active' "
                "AND rp.permission_id=:permission)"
            ),
            {"membership": grant.principal.membership_id, "permission": permission_id},
        )
        if allowed is not True:
            raise RoleConflictError()

    @staticmethod
    async def _require_actor_tenant_admin(
        transaction: TenantTransaction, grant: AuthorizationGrant
    ) -> None:
        allowed = await transaction.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM auth.membership_roles mr "
                "JOIN auth.roles r ON r.tenant_id=mr.tenant_id AND r.id=mr.role_id "
                "WHERE mr.membership_id=:membership AND r.kind='tenant_admin' "
                "AND r.status='active')"
            ),
            {"membership": grant.principal.membership_id},
        )
        if allowed is not True:
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
