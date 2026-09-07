"""Observe the tenant-context reader through the real application role.

These tests never provision tables or policies. Each connection comes from the
existing PostgreSQL fixture; every setting assignment uses a bound value inside
an active transaction.
"""

from __future__ import annotations

from uuid import UUID, uuid7

import pytest
from sqlalchemy import Connection, text


def current_tenant_id(connection: Connection) -> UUID | None:
    return connection.execute(text("SELECT app.current_tenant_id()")).scalar_one()


def set_transaction_tenant(connection: Connection, value: str) -> None:
    assert connection.in_transaction(), "Tenant settings must be transaction-local."
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": value},
    )


def test_missing_setting_returns_null(app_connection: Connection) -> None:
    """NullPool gives this test a fresh server connection with no custom setting."""
    assert (
        app_connection.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar_one()
        is None
    )
    assert current_tenant_id(app_connection) is None


@pytest.mark.parametrize("value", ["", "not-a-uuid", " ", "tenant-a", "'; SELECT 1; --"])
def test_empty_or_invalid_setting_returns_null(app_connection: Connection, value: str) -> None:
    set_transaction_tenant(app_connection, value)

    assert current_tenant_id(app_connection) is None
    # Handling a malformed value must not abort the caller's transaction.
    assert app_connection.execute(text("SELECT 1")).scalar_one() == 1


@pytest.mark.parametrize(
    "value",
    [
        uuid7(),
        UUID("12cbd799-cc5d-491a-83e8-a5b27d827447"),
        UUID("00000000-0000-0000-0000-000000000000"),
    ],
    ids=["uuid7", "uuid4-syntax", "nil-uuid-syntax"],
)
def test_valid_uuid_is_returned_without_tenant_lookup(
    app_connection: Connection, value: UUID
) -> None:
    """The SQL reader accepts UUID syntax; the service TenantId enforces UUIDv7."""
    set_transaction_tenant(app_connection, str(value))

    assert current_tenant_id(app_connection) == value


@pytest.mark.parametrize("commit", [True, False], ids=["commit", "rollback"])
def test_context_is_gone_after_transaction_end(app_connection: Connection, commit: bool) -> None:
    value = uuid7()
    set_transaction_tenant(app_connection, str(value))
    assert current_tenant_id(app_connection) == value

    if commit:
        app_connection.commit()
    else:
        app_connection.rollback()

    assert not app_connection.in_transaction()
    assert current_tenant_id(app_connection) is None


def test_function_metadata_is_stable_invoker_uuid_and_migration_owned(
    app_connection: Connection, migration_role: str, application_role: str
) -> None:
    function = app_connection.execute(
        text(
            "SELECT p.provolatile, p.prosecdef, "
            "pg_get_userbyid(p.proowner) AS owner, "
            "format_type(p.prorettype, NULL) AS return_type "
            "FROM pg_proc p WHERE p.oid = 'app.current_tenant_id()'::regprocedure"
        )
    ).one()

    assert function.provolatile == "s"
    assert function.prosecdef is False
    assert function.return_type == "uuid"
    assert function.owner == migration_role
    assert function.owner != application_role


def test_runtime_can_call_reader_but_cannot_create_in_app_schema(
    app_connection: Connection,
) -> None:
    permissions = app_connection.execute(
        text(
            "SELECT has_schema_privilege(current_user, 'app', 'USAGE') AS may_use, "
            "has_schema_privilege(current_user, 'app', 'CREATE') AS may_create, "
            "has_function_privilege("
            "current_user, 'app.current_tenant_id()', 'EXECUTE') AS may_execute"
        )
    ).one()

    assert permissions.may_use is True
    assert permissions.may_execute is True
    assert permissions.may_create is False


def test_function_execution_is_not_public_or_grantable_by_runtime(
    app_connection: Connection, migration_role: str, application_role: str
) -> None:
    grants = app_connection.execute(
        text(
            "SELECT acl.grantee, pg_get_userbyid(acl.grantee) AS role_name, "
            "acl.privilege_type, acl.is_grantable "
            "FROM pg_proc p "
            "CROSS JOIN LATERAL aclexplode("
            "COALESCE(p.proacl, acldefault('f', p.proowner))) acl "
            "WHERE p.oid = 'app.current_tenant_id()'::regprocedure"
        )
    ).all()

    assert grants, "Function ACLs must explicitly restrict execution."
    assert all(grant.grantee != 0 for grant in grants), "PUBLIC must have no function grant."
    assert {grant.role_name for grant in grants} == {migration_role, application_role}
    runtime_grants = [grant for grant in grants if grant.role_name == application_role]
    assert len(runtime_grants) == 1
    assert runtime_grants[0].privilege_type == "EXECUTE"
    assert runtime_grants[0].is_grantable is False
