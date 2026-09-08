"""PostgreSQL proofs for the closed, transaction-bound security audit boundary."""

from __future__ import annotations

import ast
import asyncio
import re
import secrets
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from psycopg import Error as PsycopgError
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.audit.contracts import (
    ROLE_EVENT_TYPES,
    SECURITY_EVENT_POLICIES,
    InvalidSecurityAuditEventError,
    SecurityAuditEvent,
    SecurityEventResult,
    SecurityEventType,
    SecurityReasonCode,
    SubjectKind,
)
from app.audit.schema import AUDIT_CHECKS
from app.audit.writer import SecurityAuditWriteError, SecurityEventWriter
from app.authorization.permissions import PERMISSION_CATALOG
from app.core.config import Settings
from app.models.auth_security import SecurityEvent

APPEND_SQL = text("""
    SELECT auth.append_security_event(
      CAST(:id AS uuid), CAST(:type AS text), CAST(:result AS text),
      CAST(:reason AS text), CAST(:user AS uuid), CAST(:session AS uuid),
      CAST(:membership AS uuid), CAST(:subject AS bytea), CAST(:correlation AS uuid),
      CAST(:role AS uuid), CAST(:target_membership AS uuid), CAST(:permission AS text),
      CAST(:subject_kind AS text), CAST(:subject_key_id AS smallint),
      CAST(:affected_count AS bigint))
""")


def _parameters(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "type": SecurityEventType.LOGIN_FAILURE.value,
        "result": SecurityEventResult.FAILURE.value,
        "reason": None,
        "user": None,
        "session": None,
        "membership": None,
        "subject": None,
        "correlation": uuid.uuid7(),
        "role": None,
        "target_membership": None,
        "permission": None,
        "subject_kind": None,
        "subject_key_id": None,
        "affected_count": None,
    }
    values.update(changes)
    return values


@dataclass(frozen=True)
class AuditFixture:
    migration: Engine = field(repr=False)
    users: tuple[uuid.UUID, uuid.UUID]
    tenants: tuple[uuid.UUID, uuid.UUID]
    memberships: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    sessions: tuple[uuid.UUID, uuid.UUID]


@pytest.fixture
def audit_fixture(settings: Settings) -> Iterator[AuditFixture]:
    engine = create_engine(
        settings.required_migration_database_url, poolclass=NullPool, hide_parameters=True
    )
    fixture = AuditFixture(
        engine,
        (uuid.uuid7(), uuid.uuid7()),
        (uuid.uuid7(), uuid.uuid7()),
        (uuid.uuid7(), uuid.uuid7(), uuid.uuid7()),
        (uuid.uuid7(), uuid.uuid7()),
    )
    now = datetime.now(UTC)
    try:
        with engine.begin() as db:
            for tenant in fixture.tenants:
                db.execute(
                    text(
                        "INSERT INTO public.tenants(id,slug,name_ar,name_en,status) "
                        "VALUES(:id,:slug,'Audit test','Audit test','active')"
                    ),
                    {"id": tenant, "slug": f"audit-g2-{tenant.hex}"},
                )
            for user in fixture.users:
                db.execute(
                    text(
                        "INSERT INTO auth.users(id,email,normalized_email,status) "
                        "VALUES(:id,:email,:email,'active')"
                    ),
                    {"id": user, "email": f"audit-g2-{user.hex}@example.test"},
                )
            for membership, user, tenant in (
                (fixture.memberships[0], fixture.users[0], fixture.tenants[0]),
                (fixture.memberships[1], fixture.users[0], fixture.tenants[1]),
                (fixture.memberships[2], fixture.users[1], fixture.tenants[0]),
            ):
                db.execute(
                    text(
                        "INSERT INTO auth.tenant_memberships"
                        "(id,user_id,tenant_id,status,joined_at) "
                        "VALUES(:id,:user,:tenant,'active',:now)"
                    ),
                    {"id": membership, "user": user, "tenant": tenant, "now": now},
                )
            for user, session, membership in (
                (fixture.users[0], fixture.sessions[0], fixture.memberships[0]),
                (fixture.users[1], fixture.sessions[1], fixture.memberships[2]),
            ):
                db.execute(
                    text("""
                    INSERT INTO auth.sessions(
                      id,user_id,bearer_digest,csrf_digest,security_version,created_at,
                      authenticated_at,last_seen_at,idle_expires_at,absolute_expires_at,
                      selected_membership_id,selected_membership_version)
                    VALUES(:id,:user,:bearer,:csrf,1,:now,:now,:now,:idle,:absolute,:membership,1)
                    """),
                    {
                        "id": session,
                        "user": user,
                        "bearer": secrets.token_bytes(32),
                        "csrf": secrets.token_bytes(32),
                        "now": now,
                        "idle": now + timedelta(minutes=30),
                        "absolute": now + timedelta(hours=8),
                        "membership": membership,
                    },
                )
        yield fixture
    finally:
        with engine.begin() as db:
            for user in fixture.users:
                # Test-created events only; no runtime retention capability is used.
                db.execute(text("DELETE FROM auth.security_events WHERE user_id=:id"), {"id": user})
                db.execute(text("DELETE FROM auth.sessions WHERE user_id=:id"), {"id": user})
                db.execute(
                    text("DELETE FROM auth.tenant_memberships WHERE user_id=:id"), {"id": user}
                )
                db.execute(text("DELETE FROM auth.users WHERE id=:id"), {"id": user})
            for tenant in fixture.tenants:
                db.execute(text("DELETE FROM public.tenants WHERE id=:id"), {"id": tenant})
        engine.dispose()


def test_event_catalog_constraints_and_columns_match_closed_contract(
    app_connection: Connection,
) -> None:
    constraints = {
        str(row[0]): str(row[1])
        for row in app_connection.execute(
            text("""
            SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid='auth.security_events'::regclass AND contype='c'
            """)
        ).all()
    }
    assert {f"ck_security_events_{name}" for name in AUDIT_CHECKS} <= constraints.keys()
    event_values = set(
        re.findall(r"'([^']+)'", constraints["ck_security_events_event_type_allowed"])
    )
    assert event_values == {event.value for event in SecurityEventType}
    permissions = set(
        re.findall(r"'([^']+)'", constraints["ck_security_events_permission_catalog"])
    )
    assert permissions == set(PERMISSION_CATALOG)
    columns = set(
        app_connection.execute(
            text("""
            SELECT attname FROM pg_attribute
            WHERE attrelid='auth.security_events'::regclass AND attnum>0 AND NOT attisdropped
            """)
        ).scalars()
    )
    assert columns == {
        "id",
        "created_at",
        "event_type",
        "result",
        "reason_code",
        "correlation_id",
        "user_id",
        "session_id",
        "membership_id",
        "subject_digest",
        "role_id",
        "target_membership_id",
        "permission_id",
        "subject_kind",
        "subject_key_id",
        "affected_count",
    }


def test_event_storage_is_migrator_owned_without_runtime_or_public_table_grants(
    app_connection: Connection, application_role: str, migration_role: str
) -> None:
    row = app_connection.execute(
        text("""
        SELECT pg_get_userbyid(relowner) AS owner,relrowsecurity,relforcerowsecurity,
          has_table_privilege(:app,oid,
            'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') AS access
        FROM pg_class WHERE oid='auth.security_events'::regclass
        """),
        {"app": application_role},
    ).one()
    assert row.owner == migration_role and row.owner != application_role
    assert row.access is False
    assert row.relrowsecurity is False and row.relforcerowsecurity is False
    assert (
        app_connection.scalar(
            text("""
        SELECT count(*) FROM pg_class c,
          LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
        WHERE c.oid='auth.security_events'::regclass AND a.grantee=0
        """)
        )
        == 0
    )
    assert (
        app_connection.scalar(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid='auth.security_events'::regclass AND contype='f'"
            )
        )
        == 0
    )


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT id FROM auth.security_events LIMIT 1",
        "INSERT INTO auth.security_events(id,event_type,result,correlation_id,created_at) "
        "VALUES(:id,'login_failure','failure',:correlation,clock_timestamp())",
        "UPDATE auth.security_events SET result='failure' WHERE id=:id",
        "DELETE FROM auth.security_events WHERE id=:id",
        "TRUNCATE auth.security_events",
    ],
)
def test_runtime_cannot_read_or_mutate_event_storage_directly(
    app_connection: Connection, statement: str
) -> None:
    with pytest.raises(DBAPIError) as caught, app_connection.begin_nested():
        app_connection.execute(
            text(statement), {"id": uuid.uuid7(), "correlation": str(uuid.uuid7())}
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "42501"


def test_append_and_guard_functions_have_exact_grants_and_no_rls_bypass(
    app_connection: Connection, application_role: str, migration_role: str
) -> None:
    rows = app_connection.execute(
        text("""
        SELECT proname,pg_get_userbyid(proowner) AS owner,prosecdef,proconfig,
          oidvectortypes(proargtypes) AS arguments,
          has_function_privilege(:app,oid,'EXECUTE') AS app_execute,
          has_function_privilege('public',oid,'EXECUTE') AS public_execute,
          pg_get_functiondef(oid) AS definition
        FROM pg_proc WHERE pronamespace='auth'::regnamespace
          AND proname IN ('append_security_event','validate_security_event_insert')
        ORDER BY proname
        """),
        {"app": application_role},
    ).all()
    assert len(rows) == 2
    for row in rows:
        assert row.owner == migration_role and row.prosecdef is True
        assert row.proconfig == ["search_path=pg_catalog"]
        assert row.public_execute is False
        assert row.app_execute is (row.proname == "append_security_event")
        for forbidden in ("BYPASSRLS", "ROW_SECURITY", "SET_CONFIG", "EXECUTE "):
            assert forbidden not in row.definition.upper()
    assert rows[0].arguments == (
        "uuid, text, text, text, uuid, uuid, uuid, bytea, "
        "uuid, uuid, uuid, text, text, smallint, bigint"
    )
    assert rows[1].arguments == ""
    assert (
        app_connection.scalar(
            text("""
        SELECT count(*) FROM pg_trigger WHERE tgrelid='auth.security_events'::regclass
          AND tgname='security_event_insert_guard' AND NOT tgisinternal AND tgenabled='O'
        """)
        )
        == 1
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "canary-unknown-event"},
        {"type": '{"password":"canary-nested-value"}'},
        {"result": "success"},
        {"reason": "canary-untrusted-reason"},
        {"reason": '{"password":{"v":"canary"}}'},
        {"reason": SecurityReasonCode.CSRF_MISSING.value},
        {"subject": b"a" * 32},
        {"subject": b"a" * 31, "subject_kind": "login_ip", "subject_key_id": 1},
        {"subject": b"a" * 32, "subject_kind": "canary-kind", "subject_key_id": 1},
        {"subject": b"a" * 32, "subject_kind": "login_ip", "subject_key_id": 0},
        {"affected_count": 1},
        {"permission": "tenant.unknown_resource.unknown_action"},
    ],
)
def test_raw_sql_event_inputs_are_rejected_by_closed_database_contract(
    app_connection: Connection, changes: dict[str, Any]
) -> None:
    with pytest.raises(DBAPIError) as caught, app_connection.begin_nested():
        app_connection.execute(APPEND_SQL, _parameters(**changes))
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"
    assert isinstance(caught.value.orig, PsycopgError)
    diagnostic = caught.value.orig.diag
    assert diagnostic.message_primary == "audit_event_invalid"
    assert diagnostic.message_detail is None


@pytest.mark.parametrize(
    "event_type", [*ROLE_EVENT_TYPES, SecurityEventType.SECURITY_EVENTS_PRUNED]
)
def test_reserved_role_and_retention_events_have_no_runtime_write_capability(
    app_connection: Connection, event_type: SecurityEventType
) -> None:
    with pytest.raises(DBAPIError) as caught, app_connection.begin_nested():
        app_connection.execute(
            APPEND_SQL,
            _parameters(
                type=event_type.value, result=SECURITY_EVENT_POLICIES[event_type].result.value
            ),
        )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"


@pytest.mark.parametrize(
    "mismatch",
    [
        "user_missing",
        "session_foreign",
        "membership_foreign",
        "membership_unselected",
        "session_missing",
        "membership_missing",
    ],
)
async def test_writer_rejects_forged_or_inconsistent_identity_links(
    settings: Settings, audit_fixture: AuditFixture, mismatch: str
) -> None:
    values: dict[str, Any] = {
        "event_type": SecurityEventType.TENANT_SWITCH,
        "result": SecurityEventResult.SUCCESS,
        "user_id": audit_fixture.users[0],
        "session_id": audit_fixture.sessions[0],
        "membership_id": audit_fixture.memberships[0],
    }
    if mismatch == "user_missing":
        values["user_id"] = uuid.uuid7()
    elif mismatch == "session_foreign":
        values["session_id"] = audit_fixture.sessions[1]
    elif mismatch == "membership_foreign":
        values["membership_id"] = audit_fixture.memberships[2]
    elif mismatch == "membership_unselected":
        values["membership_id"] = audit_fixture.memberships[1]
    elif mismatch == "session_missing":
        values["session_id"] = uuid.uuid7()
    else:
        values["membership_id"] = uuid.uuid7()
    engine = create_async_engine(settings.database_url, poolclass=NullPool, hide_parameters=True)
    try:
        with pytest.raises(SecurityAuditWriteError) as caught:
            async with engine.begin() as connection:
                await SecurityEventWriter(connection).write(SecurityAuditEvent(**values))
        assert str(caught.value) == "Security audit write failed."
        assert caught.value.__suppress_context__ is True
        with audit_fixture.migration.connect() as db:
            assert (
                db.scalar(
                    text("SELECT count(*) FROM auth.security_events WHERE user_id=:id"),
                    {"id": audit_fixture.users[0]},
                )
                == 0
            )
    finally:
        await engine.dispose()


async def test_writer_persists_only_closed_fields_with_internal_identifiers(
    settings: Settings, audit_fixture: AuditFixture, caplog: pytest.LogCaptureFixture
) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool, hide_parameters=True)
    event = SecurityAuditEvent(
        event_type=SecurityEventType.TENANT_SWITCH,
        result=SecurityEventResult.SUCCESS,
        user_id=audit_fixture.users[0],
        session_id=audit_fixture.sessions[0],
        membership_id=audit_fixture.memberships[0],
    )
    try:
        async with engine.begin() as connection:
            writer = SecurityEventWriter(connection)
            assert await connection.scalar(text("SELECT current_user")) != (
                await connection.scalar(
                    text(
                        "SELECT pg_get_userbyid(relowner) FROM pg_class "
                        "WHERE oid='auth.security_events'::regclass"
                    )
                )
            )
            await writer.write(event)
            await writer.write(event)
            assert repr(writer) == "<SecurityEventWriter>"
        with audit_fixture.migration.connect() as db:
            rows = (
                db.execute(
                    text("SELECT * FROM auth.security_events WHERE user_id=:id ORDER BY id"),
                    {"id": audit_fixture.users[0]},
                )
                .mappings()
                .all()
            )
        assert len(rows) == 2
        assert all(row["id"].version == 7 for row in rows)
        assert len({row["id"] for row in rows}) == 2
        assert uuid.UUID(rows[0]["correlation_id"]).version == 7
        assert rows[0]["correlation_id"] == rows[1]["correlation_id"]
        assert all(row["created_at"].tzinfo is not None for row in rows)
        assert all(row["subject_digest"] is None for row in rows)
        assert repr(event) == "<SecurityAuditEvent>"
        assert str(audit_fixture.users[0]) not in caplog.text
    finally:
        await engine.dispose()


async def test_mandatory_writer_failure_rolls_back_same_transaction_security_change(
    settings: Settings, audit_fixture: AuditFixture
) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool, hide_parameters=True)
    try:
        with pytest.raises(SecurityAuditWriteError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE auth.sessions SET revoked_at=clock_timestamp(),"
                        "revoked_reason='logout' WHERE id=:id"
                    ),
                    {"id": audit_fixture.sessions[0]},
                )
                await SecurityEventWriter(connection).write(
                    SecurityAuditEvent(
                        event_type=SecurityEventType.LOGIN_FAILURE,
                        result=SecurityEventResult.FAILURE,
                        user_id=uuid.uuid7(),
                    )
                )
        with audit_fixture.migration.connect() as db:
            row = db.execute(
                text("SELECT revoked_at,revoked_reason FROM auth.sessions WHERE id=:id"),
                {"id": audit_fixture.sessions[0]},
            ).one()
            assert row.revoked_at is None and row.revoked_reason is None
    finally:
        await engine.dispose()


def test_legacy_wrapper_replaces_client_correlation_with_internal_uuid(
    app_connection: Connection, audit_fixture: AuditFixture
) -> None:
    event_id = uuid.uuid7()
    app_connection.execute(
        text("""
        SELECT auth.record_security_event(:id,'login_failure','failure',NULL,
          CAST(:user AS uuid),NULL,NULL,NULL,:correlation)
        """),
        {
            "id": event_id,
            "user": audit_fixture.users[0],
            "correlation": "canary-client-correlation",
        },
    )
    app_connection.commit()
    with audit_fixture.migration.connect() as db:
        stored = db.scalar(
            text("SELECT correlation_id FROM auth.security_events WHERE id=:id"), {"id": event_id}
        )
    assert stored != "canary-client-correlation"
    assert uuid.UUID(stored).variant == uuid.RFC_4122


async def test_writer_rejects_unknown_fields_and_nested_secrets_without_emission(
    settings: Settings, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool, hide_parameters=True)
    canary = "canary-nested-audit-input"
    try:
        async with engine.begin() as connection:
            with pytest.raises(InvalidSecurityAuditEventError) as caught:
                event = SecurityAuditEvent(
                    event_type=SecurityEventType.LOGIN_FAILURE,
                    result=SecurityEventResult.FAILURE,
                    metadata={"password": canary, "nested": {"reset_token": canary}},
                )
                await SecurityEventWriter(connection).write(event)
            assert canary not in repr(caught.value)
            assert str(caught.value) == "Invalid security audit event."
        output = capsys.readouterr()
        assert canary not in caplog.text + output.out + output.err
        model = SecurityEvent(event_type=canary, result=canary, reason_code=canary)
        assert canary not in repr(model)
    finally:
        await engine.dispose()


async def test_writer_requires_an_existing_transaction(settings: Settings) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            with pytest.raises(SecurityAuditWriteError):
                await SecurityEventWriter(connection).write(
                    SecurityAuditEvent(
                        event_type=SecurityEventType.LOGIN_FAILURE,
                        result=SecurityEventResult.FAILURE,
                        subject_digest=b"a" * 32,
                        subject_kind=SubjectKind.LOGIN_IP,
                        subject_key_id=1,
                    )
                )
    finally:
        await engine.dispose()


def test_frozen_migration_catalogue_matches_the_runtime_contract() -> None:
    migration = (
        Path(__file__).resolve().parents[4] / "migrations/versions/0014_security_audit_contract.py"
    )
    module = ast.parse(migration.read_text(encoding="utf-8"))
    snapshot = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "AUDIT_CHECKS" for target in node.targets
        )
    )
    assert snapshot == AUDIT_CHECKS


async def test_deleting_fixture_identity_does_not_cascade_into_historical_events(
    settings: Settings, audit_fixture: AuditFixture
) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool, hide_parameters=True)
    user_id = audit_fixture.users[0]
    try:
        async with engine.begin() as connection:
            await SecurityEventWriter(connection).write(
                SecurityAuditEvent(
                    event_type=SecurityEventType.LOGOUT,
                    result=SecurityEventResult.SUCCESS,
                    user_id=user_id,
                    session_id=audit_fixture.sessions[0],
                    membership_id=audit_fixture.memberships[0],
                )
            )
        # Rollback-only fixture mutation; the historical links must remain intact.
        with audit_fixture.migration.connect() as db:
            db.execute(text("DELETE FROM auth.sessions WHERE user_id=:id"), {"id": user_id})
            db.execute(
                text("DELETE FROM auth.tenant_memberships WHERE user_id=:id"), {"id": user_id}
            )
            db.execute(text("DELETE FROM auth.users WHERE id=:id"), {"id": user_id})
            row = db.execute(
                text(
                    "SELECT user_id,session_id,membership_id "
                    "FROM auth.security_events WHERE user_id=:id"
                ),
                {"id": user_id},
            ).one()
            assert tuple(row) == (user_id, audit_fixture.sessions[0], audit_fixture.memberships[0])
    finally:
        await engine.dispose()


async def test_append_keeps_session_membership_link_stable_until_transaction_ends(
    settings: Settings, audit_fixture: AuditFixture, application_engine: Engine
) -> None:
    session_id = audit_fixture.sessions[0]
    target_membership = audit_fixture.memberships[1]

    def try_change_link() -> str | None:
        # A distinct runtime connection contends with the append transaction.
        # Both attempts are rollback-only, including the successful one.
        with application_engine.connect() as db:
            transaction = db.begin()
            try:
                db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                db.execute(
                    text(
                        "UPDATE auth.sessions SET selected_membership_id=:membership,"
                        "selected_membership_version=1 WHERE id=:id"
                    ),
                    {"id": session_id, "membership": target_membership},
                )
                assert (
                    db.scalar(
                        text("SELECT selected_membership_id FROM auth.sessions WHERE id=:id"),
                        {"id": session_id},
                    )
                    == target_membership
                )
                return None
            except DBAPIError as error:
                assert isinstance(error.orig, PsycopgError)
                return error.orig.sqlstate or "database_error"
            finally:
                transaction.rollback()

    engine = create_async_engine(settings.database_url, poolclass=NullPool, hide_parameters=True)
    loop = asyncio.get_running_loop()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await SecurityEventWriter(connection).write(
                        SecurityAuditEvent(
                            event_type=SecurityEventType.TENANT_SWITCH,
                            result=SecurityEventResult.SUCCESS,
                            user_id=audit_fixture.users[0],
                            session_id=session_id,
                            membership_id=audit_fixture.memberships[0],
                        )
                    )
                    assert await loop.run_in_executor(executor, try_change_link) == "55P03"
                finally:
                    await transaction.rollback()
                assert await loop.run_in_executor(executor, try_change_link) is None
        with audit_fixture.migration.connect() as db:
            assert (
                db.scalar(
                    text("SELECT selected_membership_id FROM auth.sessions WHERE id=:id"),
                    {"id": session_id},
                )
                == audit_fixture.memberships[0]
            )
    finally:
        await engine.dispose()
