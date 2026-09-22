"""Live role administration, concurrency, and platform-boundary contracts."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.pool import NullPool

from app.auth.tenants import AuthenticatedPrincipal
from app.authorization.contracts import AuthorizationBoundaryRequiredError, AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.authorization.service import AuthorizationDecision, AuthorizationService
from app.core.config import Settings
from app.models.authorization import RoleKey
from app.models.tenant import TenantId
from app.services.role_administration import (
    MembershipNotFoundError,
    RoleAdministrationService,
    RoleConflictError,
    RoleNotFoundError,
)
from app.services.tenant_administration import (
    TenantAdministrationService,
    TenantUserConflictError,
)
from app.tenancy.context import TenantContext

if TYPE_CHECKING:
    from tests.db.test_rbac_foundation import RbacFixture

pytest_plugins = ("tests.db.test_rbac_foundation",)


def _grant(state: RbacFixture, permission: Permission) -> AuthorizationGrant:
    return AuthorizationGrant(
        AuthenticatedPrincipal(state.user_a, state.session_a, state.membership_a, 1),
        TenantContext(TenantId(state.tenant_a)),
        PermissionId(permission.value),
    )


def _give_actor_permissions(
    state: RbacFixture, settings: Settings, *permissions: Permission
) -> uuid.UUID:
    role_id = uuid.uuid7()
    engine = create_engine(settings.database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id',CAST(:tenant AS text),true)"),
            {"tenant": state.tenant_a},
        )
        connection.execute(
            text(
                "INSERT INTO auth.roles(id,tenant_id,key,display_name) "
                "VALUES (:role,:tenant,:key,'Administration proof')"
            ),
            {"role": role_id, "tenant": state.tenant_a, "key": f"proof_{role_id.hex}"},
        )
        for permission in permissions:
            connection.execute(
                text(
                    "INSERT INTO auth.role_permissions(tenant_id,role_id,permission_id) "
                    "VALUES (:tenant,:role,:permission)"
                ),
                {
                    "tenant": state.tenant_a,
                    "role": role_id,
                    "permission": permission.value,
                },
            )
        connection.execute(
            text(
                "INSERT INTO auth.membership_roles(tenant_id,membership_id,role_id) "
                "VALUES (:tenant,:membership,:role)"
            ),
            {
                "tenant": state.tenant_a,
                "membership": state.membership_a,
                "role": role_id,
            },
        )
    engine.dispose()
    return role_id


def _tenant_admin_role(
    state: RbacFixture, settings: Settings, membership_id: uuid.UUID
) -> uuid.UUID:
    role_id = uuid.uuid7()
    engine = create_engine(settings.database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id',CAST(:tenant AS text),true)"),
            {"tenant": state.tenant_a},
        )
        connection.execute(
            text(
                "INSERT INTO auth.roles(id,tenant_id,key,display_name,kind) "
                "VALUES (:role,:tenant,'tenant_admin','Tenant Admin / مسؤول الجمعية',"
                "'tenant_admin')"
            ),
            {"role": role_id, "tenant": state.tenant_a},
        )
        connection.execute(
            text(
                "INSERT INTO auth.membership_roles(tenant_id,membership_id,role_id) "
                "VALUES (:tenant,:membership,:role)"
            ),
            {"tenant": state.tenant_a, "membership": membership_id, "role": role_id},
        )
    engine.dispose()
    return role_id


@pytest.fixture
def target_membership(rbac_fixture: RbacFixture, settings: Settings) -> Iterator[uuid.UUID]:
    user_id, membership_id = uuid.uuid7(), uuid.uuid7()
    migration = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with migration.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO auth.users(id,email,normalized_email,status) "
                "VALUES (:user,:email,:email,'active')"
            ),
            {"user": user_id, "email": f"role-target-{user_id}@example.test"},
        )
        connection.execute(
            text(
                "INSERT INTO auth.tenant_memberships(id,user_id,tenant_id,status,joined_at) "
                "VALUES (:membership,:user,:tenant,'active',now())"
            ),
            {
                "membership": membership_id,
                "user": user_id,
                "tenant": rbac_fixture.tenant_a,
            },
        )
    try:
        yield membership_id
    finally:
        runtime = create_engine(settings.database_url, poolclass=NullPool)
        with runtime.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id',CAST(:tenant AS text),true)"),
                {"tenant": rbac_fixture.tenant_a},
            )
            connection.execute(
                text("DELETE FROM auth.membership_roles WHERE membership_id=:membership"),
                {"membership": membership_id},
            )
        runtime.dispose()
        with migration.begin() as connection:
            connection.execute(
                text("DELETE FROM auth.tenant_memberships WHERE id=:membership"),
                {"membership": membership_id},
            )
            connection.execute(text("DELETE FROM auth.users WHERE id=:user"), {"user": user_id})
        migration.dispose()


async def test_create_update_disable_and_optimistic_version(
    rbac_fixture: RbacFixture,
) -> None:
    service = RoleAdministrationService()
    grant = _grant(rbac_fixture, Permission.TENANT_ROLES_MANAGE)
    created = await service.create_role(grant, RoleKey("auditor"), "Auditor")
    assert created.tenant_id == rbac_fixture.tenant_a
    assert (created.status, created.version) == ("active", 1)
    updated = await service.update_role(
        grant, created.id, expected_version=1, display_name="Senior Auditor"
    )
    assert (updated.display_name, updated.version) == ("Senior Auditor", 2)
    with pytest.raises(RoleConflictError):
        await service.update_role(grant, created.id, expected_version=1, display_name="Stale")
    disabled = await service.disable_role(grant, created.id, expected_version=2)
    assert (disabled.status, disabled.version) == ("inactive", 3)


async def test_duplicate_role_key_is_rejected(rbac_fixture: RbacFixture) -> None:
    grant = _grant(rbac_fixture, Permission.TENANT_ROLES_MANAGE)
    with pytest.raises(RoleConflictError):
        await RoleAdministrationService().create_role(grant, RoleKey("reader"), "Duplicate")


async def test_permission_assignment_and_removal_are_idempotent(
    rbac_fixture: RbacFixture, settings: Settings
) -> None:
    _give_actor_permissions(rbac_fixture, settings, Permission.TENANT_ROLES_READ)
    service = RoleAdministrationService()
    grant = _grant(rbac_fixture, Permission.TENANT_ROLES_MANAGE)
    assert await service.assign_permission(grant, rbac_fixture.role_a, Permission.TENANT_ROLES_READ)
    assert not await service.assign_permission(
        grant, rbac_fixture.role_a, Permission.TENANT_ROLES_READ
    )
    assert await service.remove_permission(grant, rbac_fixture.role_a, Permission.TENANT_ROLES_READ)
    assert not await service.remove_permission(
        grant, rbac_fixture.role_a, Permission.TENANT_ROLES_READ
    )


async def test_actor_cannot_grant_a_permission_they_do_not_possess(
    rbac_fixture: RbacFixture,
) -> None:
    grant = _grant(rbac_fixture, Permission.TENANT_ROLES_MANAGE)
    with pytest.raises(RoleConflictError):
        await RoleAdministrationService().assign_permission(
            grant, rbac_fixture.role_a, Permission.TENANT_USERS_MANAGE
        )


async def test_membership_role_assignment_and_removal_are_idempotent(
    rbac_fixture: RbacFixture, target_membership: uuid.UUID
) -> None:
    service = RoleAdministrationService()
    grant = _grant(rbac_fixture, Permission.TENANT_MEMBERSHIPS_MANAGE)
    assert await service.assign_role(grant, target_membership, rbac_fixture.role_a)
    assert not await service.assign_role(grant, target_membership, rbac_fixture.role_a)
    assert await service.remove_role(grant, target_membership, rbac_fixture.role_a)
    assert not await service.remove_role(grant, target_membership, rbac_fixture.role_a)


async def test_self_role_assignment_and_removal_are_denied(
    rbac_fixture: RbacFixture,
) -> None:
    service = RoleAdministrationService()
    grant = _grant(rbac_fixture, Permission.TENANT_MEMBERSHIPS_MANAGE)
    with pytest.raises(RoleConflictError):
        await service.assign_role(grant, rbac_fixture.membership_a, rbac_fixture.role_a)
    with pytest.raises(RoleConflictError):
        await service.remove_role(grant, rbac_fixture.membership_a, rbac_fixture.role_a)


async def test_system_admin_role_and_last_active_admin_are_protected(
    rbac_fixture: RbacFixture,
    target_membership: uuid.UUID,
    settings: Settings,
) -> None:
    role_id = _tenant_admin_role(rbac_fixture, settings, target_membership)
    service = RoleAdministrationService()
    role_grant = _grant(rbac_fixture, Permission.TENANT_ROLES_MANAGE)
    membership_grant = _grant(rbac_fixture, Permission.TENANT_MEMBERSHIPS_MANAGE)
    with pytest.raises(RoleConflictError):
        await service.update_role(role_grant, role_id, expected_version=1, display_name="Escalated")
    with pytest.raises(RoleConflictError):
        await service.assign_permission(role_grant, role_id, Permission.TENANT_USERS_READ)
    with pytest.raises(RoleConflictError):
        await service.remove_role(membership_grant, target_membership, role_id)
    user_grant = _grant(rbac_fixture, Permission.TENANT_USERS_MANAGE)
    with pytest.raises(TenantUserConflictError):
        await TenantAdministrationService().set_membership_status(
            user_grant,
            target_membership,
            status="suspended",
            expected_version=1,
        )


async def test_invitation_is_idempotent_and_tenant_scoped(
    rbac_fixture: RbacFixture, settings: Settings
) -> None:
    service = TenantAdministrationService()
    grant = _grant(rbac_fixture, Permission.TENANT_USERS_INVITE)
    email = f"invite-{uuid.uuid7()}@example.test"
    first = await service.invite(grant, email)
    second = await service.invite(grant, email)
    assert second == first
    read_grant = _grant(rbac_fixture, Permission.TENANT_USERS_READ)
    listed = await service.list_users(read_grant)
    invited = next(item for item in listed if item.membership_id == first)
    assert invited.email == email and invited.membership_status == "pending"
    migration = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with migration.begin() as connection:
        user_id = connection.scalar(
            text("SELECT user_id FROM auth.tenant_memberships WHERE id=:membership"),
            {"membership": first},
        )
        connection.execute(
            text("DELETE FROM auth.tenant_memberships WHERE id=:membership"),
            {"membership": first},
        )
        connection.execute(text("DELETE FROM auth.users WHERE id=:user"), {"user": user_id})
    migration.dispose()


async def test_cross_tenant_role_membership_and_idor_are_non_disclosing(
    rbac_fixture: RbacFixture,
) -> None:
    service = RoleAdministrationService()
    role_grant = _grant(rbac_fixture, Permission.TENANT_ROLES_MANAGE)
    member_grant = _grant(rbac_fixture, Permission.TENANT_MEMBERSHIPS_MANAGE)
    with pytest.raises(RoleNotFoundError):
        await service.assign_permission(
            role_grant, rbac_fixture.role_b, Permission.TENANT_ROLES_READ
        )
    with pytest.raises(RoleNotFoundError):
        await service.update_role(
            role_grant, rbac_fixture.role_b, expected_version=1, display_name="Foreign"
        )
    with pytest.raises(MembershipNotFoundError):
        await service.assign_role(member_grant, rbac_fixture.membership_b, rbac_fixture.role_a)
    with pytest.raises(RoleNotFoundError):
        await service.assign_role(member_grant, rbac_fixture.membership_a, rbac_fixture.role_b)


async def test_inactive_role_and_stale_membership_are_rejected(
    rbac_fixture: RbacFixture, settings: Settings, target_membership: uuid.UUID
) -> None:
    _give_actor_permissions(rbac_fixture, settings, Permission.TENANT_ROLES_READ)
    service = RoleAdministrationService()
    role_grant = _grant(rbac_fixture, Permission.TENANT_ROLES_MANAGE)
    member_grant = _grant(rbac_fixture, Permission.TENANT_MEMBERSHIPS_MANAGE)
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE auth.tenant_memberships SET status='suspended' WHERE id=:membership"),
            {"membership": target_membership},
        )
    engine.dispose()
    with pytest.raises(MembershipNotFoundError):
        await service.assign_role(member_grant, target_membership, rbac_fixture.role_a)

    # The next assertion isolates inactive-role behavior with a current actor.
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE auth.tenant_memberships SET status='active' WHERE id=:membership"),
            {"membership": target_membership},
        )
    engine.dispose()
    await service.disable_role(role_grant, rbac_fixture.role_a, expected_version=1)
    with pytest.raises(RoleConflictError):
        await service.assign_permission(
            role_grant, rbac_fixture.role_a, Permission.TENANT_ROLES_READ
        )


async def test_concurrent_permission_updates_preserve_both_changes(
    rbac_fixture: RbacFixture, settings: Settings
) -> None:
    _give_actor_permissions(
        rbac_fixture,
        settings,
        Permission.TENANT_ROLES_READ,
        Permission.TENANT_MEMBERSHIPS_READ,
    )
    service = RoleAdministrationService()
    grant = _grant(rbac_fixture, Permission.TENANT_ROLES_MANAGE)
    results = await asyncio.gather(
        service.assign_permission(grant, rbac_fixture.role_a, Permission.TENANT_ROLES_READ),
        service.assign_permission(grant, rbac_fixture.role_a, Permission.TENANT_MEMBERSHIPS_READ),
    )
    assert results == [True, True]


async def test_concurrent_role_assignment_creates_one_row(
    rbac_fixture: RbacFixture, target_membership: uuid.UUID
) -> None:
    service = RoleAdministrationService()
    grant = _grant(rbac_fixture, Permission.TENANT_MEMBERSHIPS_MANAGE)
    results = await asyncio.gather(
        service.assign_role(grant, target_membership, rbac_fixture.role_a),
        service.assign_role(grant, target_membership, rbac_fixture.role_a),
    )
    assert sorted(results) == [False, True]


async def test_permission_removal_and_role_disable_change_authorization_immediately(
    rbac_fixture: RbacFixture, settings: Settings
) -> None:
    proof_role = _give_actor_permissions(rbac_fixture, settings, Permission.TENANT_ROLES_READ)
    service = RoleAdministrationService()
    role_grant = _grant(rbac_fixture, Permission.TENANT_ROLES_MANAGE)
    principal = role_grant.principal
    context = role_grant.tenant_context
    permission = PermissionId(Permission.TENANT_ROLES_READ.value)
    await service.assign_permission(role_grant, rbac_fixture.role_a, Permission.TENANT_ROLES_READ)
    engine = create_engine(settings.database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id',CAST(:tenant AS text),true)"),
            {"tenant": rbac_fixture.tenant_a},
        )
        connection.execute(
            text(
                "INSERT INTO auth.membership_roles(tenant_id,membership_id,role_id) "
                "VALUES (:tenant,:membership,:role)"
            ),
            {
                "tenant": rbac_fixture.tenant_a,
                "membership": rbac_fixture.membership_a,
                "role": rbac_fixture.role_a,
            },
        )
        connection.execute(
            text(
                "DELETE FROM auth.role_permissions "
                "WHERE role_id=:role AND permission_id=:permission"
            ),
            {"role": proof_role, "permission": Permission.TENANT_ROLES_READ.value},
        )
    engine.dispose()
    authorizer = AuthorizationService()
    assert await authorizer.authorize(principal, context, permission) is AuthorizationDecision.ALLOW
    await service.remove_permission(role_grant, rbac_fixture.role_a, Permission.TENANT_ROLES_READ)
    assert await authorizer.authorize(principal, context, permission) is AuthorizationDecision.DENY
    engine = create_engine(settings.database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id',CAST(:tenant AS text),true)"),
            {"tenant": rbac_fixture.tenant_a},
        )
        connection.execute(
            text(
                "INSERT INTO auth.role_permissions(tenant_id,role_id,permission_id) "
                "VALUES (:tenant,:role,:permission)"
            ),
            {
                "tenant": rbac_fixture.tenant_a,
                "role": proof_role,
                "permission": Permission.TENANT_ROLES_READ.value,
            },
        )
    engine.dispose()
    await service.assign_permission(role_grant, rbac_fixture.role_a, Permission.TENANT_ROLES_READ)
    engine = create_engine(settings.database_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id',CAST(:tenant AS text),true)"),
            {"tenant": rbac_fixture.tenant_a},
        )
        connection.execute(
            text(
                "DELETE FROM auth.role_permissions "
                "WHERE role_id=:role AND permission_id=:permission"
            ),
            {"role": proof_role, "permission": Permission.TENANT_ROLES_READ.value},
        )
    engine.dispose()
    await service.disable_role(role_grant, rbac_fixture.role_a, expected_version=1)
    assert await authorizer.authorize(principal, context, permission) is AuthorizationDecision.DENY


async def test_unauthorized_and_platform_grants_cannot_administer_roles(
    rbac_fixture: RbacFixture,
) -> None:
    service = RoleAdministrationService()
    with pytest.raises(AuthorizationBoundaryRequiredError):
        await service.create_role(None, RoleKey("blocked"), "Blocked")  # type: ignore[arg-type]
    platform_grant = _grant(rbac_fixture, Permission.PLATFORM_TENANTS_MANAGE)
    with pytest.raises(AuthorizationBoundaryRequiredError):
        await service.create_role(platform_grant, RoleKey("platform"), "Platform")


def test_membership_guards_are_narrow_and_runtime_has_no_rls_bypass(
    app_connection: Connection, migration_role: str, application_role: str
) -> None:
    function = app_connection.execute(
        text(
            "SELECT p.prosecdef,pg_get_userbyid(p.proowner) owner,p.proconfig,"
            "pg_get_functiondef(p.oid) definition "
            "FROM pg_proc p WHERE p.oid="
            "'auth.is_active_membership_in_tenant(uuid,uuid)'::regprocedure"
        )
    ).one()
    assert function.prosecdef is True and function.owner == migration_role
    assert function.proconfig == ["search_path=pg_catalog"]
    lowered = function.definition.lower()
    assert "dynamic" not in lowered and "set_config" not in lowered
    assert app_connection.scalar(
        text(
            "SELECT has_function_privilege(:app,"
            "'auth.is_active_membership_in_tenant(uuid,uuid)','EXECUTE')"
        ),
        {"app": application_role},
    )
    assert not app_connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_proc p "
            "CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl, acldefault('f',p.proowner))) a "
            "WHERE p.oid='auth.is_active_membership_in_tenant(uuid,uuid)'::regprocedure "
            "AND a.grantee=0 AND a.privilege_type='EXECUTE')"
        )
    )
    admin_guard = app_connection.execute(
        text(
            "SELECT p.prosecdef,pg_get_userbyid(p.proowner) owner,p.proconfig,"
            "pg_get_functiondef(p.oid) definition "
            "FROM pg_proc p WHERE p.oid="
            "'auth.has_other_active_tenant_admin(uuid,uuid)'::regprocedure"
        )
    ).one()
    assert admin_guard.prosecdef is True and admin_guard.owner == migration_role
    assert admin_guard.proconfig == ["search_path=pg_catalog"]
    lowered = admin_guard.definition.lower()
    assert "execute " not in lowered and "set_config" not in lowered
    assert app_connection.scalar(
        text(
            "SELECT has_function_privilege(:app,"
            "'auth.has_other_active_tenant_admin(uuid,uuid)','EXECUTE')"
        ),
        {"app": application_role},
    )
    assert not app_connection.scalar(
        text(
            "SELECT has_function_privilege('public',"
            "'auth.has_other_active_tenant_admin(uuid,uuid)','EXECUTE')"
        )
    )
    flags = app_connection.execute(
        text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
    ).one()
    assert tuple(flags) == (False, False)
