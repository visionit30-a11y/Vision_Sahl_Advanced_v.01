"""Blocking role, ownership, privileges and live RLS-completeness contracts."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from tests.db.rls_catalog import assert_tenant_catalog, normalized_predicate
from tests.db.rls_probe import Probe

TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "MAINTAIN",
)


@pytest.mark.parametrize(
    "expression",
    [
        "tenant_id = app.current_tenant_id()",
        "(tenant_id = app.current_tenant_id())",
        "((tenant_id = app.current_tenant_id()))",
    ],
)
def test_predicate_normalization_accepts_only_irrelevant_outer_grouping(expression: str) -> None:
    assert normalized_predicate(expression) == "tenant_id=app.current_tenant_id()"


@pytest.mark.parametrize(
    "expression",
    [
        "tenant_id = (app).current_tenant_id",
        "tenant_id = app.current_tenant_id",
        "tenant_id = app.current_tenant_id() OR true",
        "true",
    ],
)
def test_predicate_normalization_preserves_function_calls_and_extra_clauses(
    expression: str,
) -> None:
    assert normalized_predicate(expression) != "tenant_id=app.current_tenant_id()"


def test_discovered_production_tenant_tables_obey_the_contract(
    app_connection: Connection, application_role: str, migration_role: str
) -> None:
    """The approved membership exception stays visible to the catalogue guard."""
    discovered = assert_tenant_catalog(
        app_connection, application_role=application_role, migration_role=migration_role
    )
    assert discovered == [
        "auth.membership_roles",
        "auth.role_permissions",
        "auth.roles",
        "auth.tenant_memberships",
    ]


def test_discovery_enforces_the_contract_on_a_real_tenant_owned_table(
    app_connection: Connection, application_role: str, migration_role: str, probe: Probe
) -> None:
    discovered = assert_tenant_catalog(
        app_connection, application_role=application_role, migration_role=migration_role
    )
    assert "auth.tenant_memberships" in discovered
    assert "public.tenant_scoped_probe" in discovered
    assert "public.tenants" not in discovered


@pytest.fixture
def migration_connection(
    settings: Settings, migration_role: str, probe: Probe
) -> Iterator[Connection]:
    """Only mutate the probe, and always roll back even when the assertion passes."""
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                assert connection.scalar(text("SELECT current_user")) == migration_role
                yield connection
            finally:
                if transaction.is_active:
                    transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("statements", "reason"),
    [
        (
            ["ALTER TABLE public.tenant_scoped_probe DISABLE ROW LEVEL SECURITY"],
            "ENABLE ROW LEVEL SECURITY",
        ),
        (
            ["ALTER TABLE public.tenant_scoped_probe NO FORCE ROW LEVEL SECURITY"],
            "FORCE ROW LEVEL SECURITY",
        ),
        (
            ["DROP POLICY tenant_isolation ON public.tenant_scoped_probe"],
            "exactly one isolation policy",
        ),
        (
            [
                "DROP POLICY tenant_isolation ON public.tenant_scoped_probe",
                "CREATE POLICY tenant_isolation ON public.tenant_scoped_probe "
                "FOR ALL TO sahl_app USING (tenant_id = app.current_tenant_id())",
            ],
            "explicit WITH CHECK",
        ),
        (
            ["ALTER POLICY tenant_isolation ON public.tenant_scoped_probe USING (true)"],
            "USING must be",
        ),
        (
            [
                "CREATE POLICY extra_access ON public.tenant_scoped_probe "
                "FOR ALL TO sahl_app USING (true) WITH CHECK (true)"
            ],
            "exactly one isolation policy",
        ),
        (
            ["ALTER TABLE public.tenant_scoped_probe ALTER COLUMN tenant_id DROP NOT NULL"],
            "UUID NOT NULL",
        ),
    ],
    ids=[
        "disabled",
        "not-forced",
        "missing-policy",
        "missing-check",
        "broad-using",
        "extra-policy",
        "nullable",
    ],
)
def test_catalog_guard_rejects_weakened_probe_metadata(
    migration_connection: Connection,
    application_role: str,
    migration_role: str,
    statements: list[str],
    reason: str,
) -> None:
    # Metadata changes are invisible to other transactions until commit; inspect
    # them through this same owner connection, then the fixture rolls them back.
    for statement in statements:
        migration_connection.exec_driver_sql(statement)
    with pytest.raises(AssertionError, match=reason):
        assert_tenant_catalog(
            migration_connection,
            application_role=application_role,
            migration_role=migration_role,
        )


@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        (
            "ALTER TABLE auth.tenant_memberships ENABLE ROW LEVEL SECURITY",
            "must not declare tenant RLS",
        ),
        (
            "ALTER TABLE auth.tenant_memberships "
            "DROP CONSTRAINT fk_tenant_memberships_tenant_id_tenants",
            "must reference public.tenants",
        ),
        (
            "ALTER TABLE auth.tenant_memberships ADD COLUMN business_payload text",
            "columns must match",
        ),
        (
            "GRANT SELECT ON auth.tenant_memberships TO sahl_app",
            "runtime must have no direct data privileges",
        ),
        (
            "GRANT SELECT ON auth.tenant_memberships TO PUBLIC",
            "PUBLIC must have no direct data privileges",
        ),
    ],
    ids=["rls-added", "tenant-fk-dropped", "business-column", "runtime-grant", "public-grant"],
)
def test_catalog_guard_rejects_a_broadened_membership_exception(
    migration_connection: Connection,
    application_role: str,
    migration_role: str,
    statement: str,
    reason: str,
) -> None:
    migration_connection.exec_driver_sql(statement)
    with pytest.raises(AssertionError, match=reason):
        assert_tenant_catalog(
            migration_connection,
            application_role=application_role,
            migration_role=migration_role,
        )


def test_runtime_has_no_elevated_flags_or_role_memberships(app_connection: Connection) -> None:
    flags = app_connection.execute(
        text(
            "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
            "FROM pg_roles WHERE rolname = current_user"
        )
    ).one()
    assert tuple(flags) == (False, False, False, False)
    memberships = app_connection.scalar(
        text(
            "SELECT count(*) FROM pg_auth_members "
            "WHERE member = (SELECT oid FROM pg_roles WHERE rolname = current_user)"
        )
    )
    assert memberships == 0


def test_runtime_owns_no_relations_schemas_functions_types_or_databases(
    app_connection: Connection,
) -> None:
    ownership = app_connection.execute(
        text(
            "WITH runtime AS (SELECT oid FROM pg_roles WHERE rolname = current_user) "
            "SELECT 'relation' AS kind, count(*) AS object_count "
            "FROM pg_class, runtime WHERE relowner = runtime.oid "
            "UNION ALL SELECT 'schema', count(*) FROM pg_namespace, runtime "
            "WHERE nspowner = runtime.oid "
            "UNION ALL SELECT 'function', count(*) FROM pg_proc, runtime "
            "WHERE proowner = runtime.oid "
            "UNION ALL SELECT 'type', count(*) FROM pg_type, runtime WHERE typowner = runtime.oid "
            "UNION ALL SELECT 'database', count(*) FROM pg_database, runtime "
            "WHERE datdba = runtime.oid"
        )
    ).all()
    assert {row.kind: row.object_count for row in ownership} == {
        "relation": 0,
        "schema": 0,
        "function": 0,
        "type": 0,
        "database": 0,
    }


def test_runtime_cannot_create_database_schemas_or_objects_in_any_user_schema(
    app_connection: Connection,
) -> None:
    assert (
        app_connection.scalar(
            text("SELECT has_database_privilege(current_user, current_database(), 'CREATE')")
        )
        is False
    )
    writable = app_connection.execute(
        text(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname !~ '^pg_' AND nspname <> 'information_schema' "
            "AND has_schema_privilege(current_user, oid, 'CREATE')"
        )
    ).all()
    assert writable == []


def test_probe_has_exactly_non_grantable_crud_for_runtime_and_no_public_access(
    app_connection: Connection, application_role: str, migration_role: str, probe: Probe
) -> None:
    grants = app_connection.execute(
        text(
            "SELECT acl.grantee, pg_get_userbyid(acl.grantee) AS role_name, "
            "acl.privilege_type, acl.is_grantable "
            "FROM pg_class c CROSS JOIN LATERAL "
            "aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) acl "
            "WHERE c.oid = 'public.tenant_scoped_probe'::regclass"
        )
    ).all()
    assert all(grant.grantee != 0 for grant in grants)
    assert {grant.role_name for grant in grants} == {migration_role, application_role}
    runtime = [grant for grant in grants if grant.role_name == application_role]
    assert {grant.privilege_type for grant in runtime} == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert all(not grant.is_grantable for grant in runtime)
    for privilege in TABLE_PRIVILEGES:
        allowed = app_connection.scalar(
            text(
                "SELECT has_table_privilege(current_user, 'public.tenant_scoped_probe', :privilege)"
            ),
            {"privilege": privilege},
        )
        assert allowed is (privilege in {"SELECT", "INSERT", "UPDATE", "DELETE"}), privilege
    column_grants = app_connection.scalar(
        text(
            "SELECT count(*) FROM pg_attribute a "
            "CROSS JOIN LATERAL aclexplode(a.attacl) acl "
            "WHERE a.attrelid = 'public.tenant_scoped_probe'::regclass "
            "AND (acl.grantee = 0 OR acl.grantee = "
            "(SELECT oid FROM pg_roles WHERE rolname = current_user))"
        )
    )
    assert column_grants == 0


def test_tenants_remains_platform_owned_without_runtime_data_grants(
    app_connection: Connection, migration_role: str
) -> None:
    table = app_connection.execute(
        text(
            "SELECT pg_get_userbyid(relowner) AS owner, relrowsecurity, relforcerowsecurity "
            "FROM pg_class WHERE oid = 'public.tenants'::regclass"
        )
    ).one()
    assert table.owner == migration_role
    assert table.relrowsecurity is False
    assert table.relforcerowsecurity is False
    assert (
        app_connection.scalar(
            text("SELECT count(*) FROM pg_policy WHERE polrelid = 'public.tenants'::regclass")
        )
        == 0
    )
    assert (
        app_connection.scalar(
            text(
                "SELECT count(*) FROM pg_attribute WHERE attrelid = 'public.tenants'::regclass "
                "AND attname = 'tenant_id' AND NOT attisdropped"
            )
        )
        == 0
    )
    for privilege in TABLE_PRIVILEGES:
        assert (
            app_connection.scalar(
                text("SELECT has_table_privilege(current_user, 'public.tenants', :privilege)"),
                {"privilege": privilege},
            )
            is False
        ), privilege
    for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
        assert (
            app_connection.scalar(
                text("SELECT has_any_column_privilege(current_user, 'public.tenants', :privilege)"),
                {"privilege": privilege},
            )
            is False
        ), privilege


def test_no_default_acl_implicitly_grants_runtime_or_public_table_access(
    app_connection: Connection,
) -> None:
    broad_defaults = app_connection.execute(
        text(
            "SELECT d.defaclobjtype, acl.privilege_type "
            "FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) acl "
            "WHERE acl.grantee = (SELECT oid FROM pg_roles WHERE rolname = current_user) "
            "OR (acl.grantee = 0 AND d.defaclobjtype IN ('r', 'S'))"
        )
    ).all()
    assert broad_defaults == []
