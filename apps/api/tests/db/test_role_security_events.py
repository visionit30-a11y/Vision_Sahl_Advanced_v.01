"""Actual role mutation proofs, mandatory rollback, and fixed privilege boundaries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.audit.contracts import SecurityAuditEvent, SecurityEventResult, SecurityEventType
from app.audit.writer import SecurityAuditWriteError, SecurityEventWriter
from app.authorization.permissions import Permission
from app.core.config import Settings
from app.db.tenant_transaction import tenant_transaction
from app.models.authorization import RoleKey
from app.services.role_administration import RoleAdministrationService
from tests.db.test_role_administration import _grant

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from tests.db.test_rbac_foundation import RbacFixture

pytest_plugins = ("tests.db.test_rbac_foundation",)


def _events(settings: Settings, state: RbacFixture) -> list[str]:
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    try:
        with engine.connect() as db:
            return list(
                db.scalars(
                    text(
                        "SELECT event_type FROM auth.security_events WHERE "
                        "user_id=:user ORDER BY created_at,id"
                    ),
                    {"user": state.user_a},
                )
            )
    finally:
        engine.dispose()


def _event(state: RbacFixture, role: uuid.UUID | None = None) -> SecurityAuditEvent:
    return SecurityAuditEvent(
        event_type=SecurityEventType.ROLE_UPDATED,
        result=SecurityEventResult.SUCCESS,
        user_id=state.user_a,
        session_id=state.session_a,
        membership_id=state.membership_a,
        role_id=role or state.role_a,
    )


async def test_every_role_event_once_and_noop_assignments_emit_nothing(
    rbac_fixture: RbacFixture, settings: Settings
) -> None:
    s = RoleAdministrationService()
    state = rbac_fixture
    role_grant = _grant(state, Permission.TENANT_ROLES_MANAGE)
    member_grant = _grant(state, Permission.TENANT_MEMBERSHIPS_MANAGE)
    created = await s.create_role(role_grant, RoleKey("audit_probe"), "Audit Probe")
    await s.update_role(role_grant, created.id, expected_version=1, display_name="Updated")
    assert await s.assign_permission(role_grant, created.id, Permission.TENANT_ROLES_READ)
    assert not await s.assign_permission(role_grant, created.id, Permission.TENANT_ROLES_READ)
    assert await s.remove_permission(role_grant, created.id, Permission.TENANT_ROLES_READ)
    assert not await s.remove_permission(role_grant, created.id, Permission.TENANT_ROLES_READ)
    assert await s.assign_role(member_grant, state.membership_a, created.id)
    assert not await s.assign_role(member_grant, state.membership_a, created.id)
    assert await s.remove_role(member_grant, state.membership_a, created.id)
    assert not await s.remove_role(member_grant, state.membership_a, created.id)
    await s.disable_role(role_grant, created.id, expected_version=2)
    assert _events(settings, state) == [
        "role_created",
        "role_updated",
        "role_permission_assigned",
        "role_permission_removed",
        "membership_role_assigned",
        "membership_role_removed",
        "role_disabled",
    ]


@pytest.mark.parametrize(
    "operation",
    [
        "create",
        "update",
        "disable",
        "assign_permission",
        "remove_permission",
        "assign_role",
        "remove_role",
    ],
)
async def test_mandatory_event_failure_rolls_back_each_role_change(
    operation: str, rbac_fixture: RbacFixture, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = RoleAdministrationService()
    state = rbac_fixture
    grant = _grant(state, Permission.TENANT_ROLES_MANAGE)
    member = _grant(state, Permission.TENANT_MEMBERSHIPS_MANAGE)
    if operation == "remove_permission":
        await s.assign_permission(grant, state.role_a, Permission.TENANT_ROLES_READ)
    if operation == "remove_role":
        await s.assign_role(member, state.membership_a, state.role_a)
    async with tenant_transaction(grant.tenant_context) as tx:
        before = (
            await tx.execute(
                text("SELECT id,key,display_name,status,version FROM auth.roles ORDER BY id")
            )
        ).all()
        permissions = (
            await tx.execute(
                text(
                    "SELECT role_id,permission_id FROM auth.role_permissions "
                    "ORDER BY role_id,permission_id"
                )
            )
        ).all()
        memberships = (
            await tx.execute(
                text(
                    "SELECT membership_id,role_id FROM auth.membership_roles "
                    "ORDER BY membership_id,role_id"
                )
            )
        ).all()
    previous = _events(settings, state)

    async def fail(self: SecurityEventWriter, event: SecurityAuditEvent) -> None:
        raise SecurityAuditWriteError()

    monkeypatch.setattr(SecurityEventWriter, "write", fail)
    with pytest.raises(SecurityAuditWriteError):
        match operation:
            case "create":
                await s.create_role(grant, RoleKey("rollback_probe"), "Rollback")
            case "update":
                await s.update_role(
                    grant, state.role_a, expected_version=1, display_name="Rollback"
                )
            case "disable":
                await s.disable_role(grant, state.role_a, expected_version=1)
            case "assign_permission":
                await s.assign_permission(grant, state.role_a, Permission.TENANT_ROLES_READ)
            case "remove_permission":
                await s.remove_permission(grant, state.role_a, Permission.TENANT_ROLES_READ)
            case "assign_role":
                await s.assign_role(member, state.membership_a, state.role_a)
            case "remove_role":
                await s.remove_role(member, state.membership_a, state.role_a)
    async with tenant_transaction(grant.tenant_context) as tx:
        assert (
            await tx.execute(
                text("SELECT id,key,display_name,status,version FROM auth.roles ORDER BY id")
            )
        ).all() == before
        assert (
            await tx.execute(
                text(
                    "SELECT role_id,permission_id FROM auth.role_permissions "
                    "ORDER BY role_id,permission_id"
                )
            )
        ).all() == permissions
        assert (
            await tx.execute(
                text(
                    "SELECT membership_id,role_id FROM auth.membership_roles "
                    "ORDER BY membership_id,role_id"
                )
            )
        ).all() == memberships
    assert _events(settings, state) == previous


async def test_unconsumed_attested_intent_prevents_commit(
    rbac_fixture: RbacFixture, settings: Settings
) -> None:
    state = rbac_fixture
    grant = _grant(state, Permission.TENANT_ROLES_MANAGE)
    with pytest.raises(DBAPIError):
        async with tenant_transaction(grant.tenant_context) as tx:
            w = SecurityEventWriter(tx)
            await w.prepare_role(_event(state), 1)
            await tx.execute(
                text(
                    "UPDATE auth.roles SET "
                    "display_name='Uncommitted',version=version+1 WHERE "
                    "id=:id"
                ),
                {"id": state.role_a},
            )
    async with tenant_transaction(grant.tenant_context) as tx:
        assert (
            await tx.scalar(
                text("SELECT version FROM auth.roles WHERE id=:id"), {"id": state.role_a}
            )
            == 1
        )
    assert _events(settings, state) == []


async def test_cancel_cannot_discard_attested_mutation(rbac_fixture: RbacFixture) -> None:
    state = rbac_fixture
    grant = _grant(state, Permission.TENANT_ROLES_MANAGE)
    event = _event(state)
    with pytest.raises(SecurityAuditWriteError):
        async with tenant_transaction(grant.tenant_context) as tx:
            w = SecurityEventWriter(tx)
            await w.prepare_role(event, 1)
            await tx.execute(
                text("UPDATE auth.roles SET version=version+1 WHERE id=:id"), {"id": state.role_a}
            )
            await w.cancel_role(event)


async def test_append_without_actual_mutation_rejected(rbac_fixture: RbacFixture) -> None:
    state = rbac_fixture
    grant = _grant(state, Permission.TENANT_ROLES_MANAGE)
    event = _event(state)
    with pytest.raises(SecurityAuditWriteError):
        async with tenant_transaction(grant.tenant_context) as tx:
            w = SecurityEventWriter(tx)
            await w.prepare_role(event, 1)
            await w.write(event)


async def test_cross_tenant_role_proof_cannot_be_forged(
    rbac_fixture: RbacFixture, settings: Settings
) -> None:
    state = rbac_fixture
    grant = _grant(state, Permission.TENANT_ROLES_MANAGE)
    foreign = _event(state, state.role_b)
    with pytest.raises(DBAPIError):
        async with tenant_transaction(grant.tenant_context) as tx:
            w = SecurityEventWriter(tx)
            await w.prepare_role(foreign, 1)
            await tx.execute(
                text("UPDATE auth.roles SET version=version+1 WHERE id=:id"), {"id": state.role_a}
            )
    assert _events(settings, state) == []


@pytest.mark.parametrize("bad_version", [0, 2])
async def test_stale_actor_membership_cannot_arm_event(
    bad_version: int, rbac_fixture: RbacFixture
) -> None:
    state = rbac_fixture
    grant = _grant(state, Permission.TENANT_ROLES_MANAGE)
    with pytest.raises(SecurityAuditWriteError):
        async with tenant_transaction(grant.tenant_context) as tx:
            await SecurityEventWriter(tx).prepare_role(_event(state), bad_version)


def test_private_intents_and_functions_have_minimum_privileges(
    app_connection: Connection, application_role: str, migration_role: str, settings: Settings
) -> None:
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert not app_connection.scalar(
            text("SELECT has_table_privilege(:role,'auth.role_security_event_intents',:privilege)"),
            {"role": application_role, "privilege": privilege},
        )
    assert not app_connection.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM pg_class c CROSS JOIN LATERAL "
            "aclexplode(c.relacl) a WHERE "
            "c.oid='auth.role_security_event_intents'::regclass AND "
            "a.grantee=0)"
        )
    )
    rows = app_connection.execute(
        text(
            "SELECT "
            "proname,prosecdef,pg_get_userbyid(proowner),proconfig,pg_get_functiondef(oid) "
            "FROM pg_proc WHERE pronamespace='auth'::regnamespace AND proname "
            "IN "
            "('prepare_role_security_event','cancel_role_security_event','attest_role_security_change','require_consumed_role_security_event')"
        )
    ).all()
    assert len(rows) == 4
    for name, definer, owner, config, definition in rows:
        assert definer is True and owner == migration_role and config == ["search_path=pg_catalog"]
        lowered = definition.lower()
        assert (
            "from auth.roles" not in lowered
            and "set_config" not in lowered
            and "execute " not in lowered
        )
        assert not app_connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_proc p CROSS JOIN LATERAL "
                "aclexplode(p.proacl) a WHERE "
                "p.pronamespace='auth'::regnamespace AND p.proname=:name AND "
                "a.grantee=0)"
            ),
            {"name": name},
        )
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    try:
        with engine.connect() as db:
            assert db.scalar(text("SELECT count(*) FROM auth.role_security_event_intents")) == 0
    finally:
        engine.dispose()
