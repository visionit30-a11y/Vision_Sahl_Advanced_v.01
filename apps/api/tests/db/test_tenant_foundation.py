"""Read the migrated tenant foundation and its effective privileges from PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy import Connection, text


@pytest.mark.parametrize(("migration", "expected"), [(True, True), (False, False)])
def test_only_the_migration_role_can_create_database_schemas(
    app_connection: Connection,
    application_role: str,
    migration_role: str,
    migration: bool,
    expected: bool,
) -> None:
    role = migration_role if migration else application_role
    actual = app_connection.execute(
        text("SELECT has_database_privilege(:role, current_database(), 'CREATE')"),
        {"role": role},
    ).scalar_one()
    assert actual is expected


@pytest.mark.parametrize("schema", ["public", "app"])
def test_foundation_schemas_belong_to_migrator_and_runtime_cannot_create(
    app_connection: Connection, migration_role: str, schema: str
) -> None:
    row = app_connection.execute(
        text(
            "SELECT pg_get_userbyid(nspowner) AS owner, "
            "has_schema_privilege(current_user, oid, 'CREATE') AS may_create "
            "FROM pg_namespace WHERE nspname = :schema"
        ),
        {"schema": schema},
    ).one()
    assert row.owner == migration_role
    assert row.may_create is False


def test_tenants_exists_and_is_owned_by_the_migration_role(
    app_connection: Connection, migration_role: str
) -> None:
    owner = app_connection.execute(
        text(
            "SELECT pg_get_userbyid(c.relowner) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = 'tenants' AND c.relkind = 'r'"
        )
    ).scalar_one()
    assert owner == migration_role


def test_runtime_keeps_all_four_restricted_role_attributes(app_connection: Connection) -> None:
    flags = app_connection.execute(
        text(
            "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
            "FROM pg_roles WHERE rolname = current_user"
        )
    ).one()
    assert tuple(flags) == (False, False, False, False)
