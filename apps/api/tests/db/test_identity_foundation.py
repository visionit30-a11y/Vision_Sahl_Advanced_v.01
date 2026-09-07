"""Live PostgreSQL contract for the Phase 2B identity foundation."""

from __future__ import annotations

from sqlalchemy import Connection, text

TABLES = ("users", "tenant_memberships", "password_credentials")


def test_auth_schema_and_tables_are_migrator_owned(
    app_connection: Connection, migration_role: str
) -> None:
    schema = app_connection.execute(
        text(
            "SELECT pg_get_userbyid(nspowner) AS owner, "
            "has_schema_privilege(current_user, oid, 'USAGE') AS may_use, "
            "has_schema_privilege(current_user, oid, 'CREATE') AS may_create "
            "FROM pg_namespace WHERE nspname = 'auth'"
        )
    ).one()
    assert schema.owner == migration_role
    assert (schema.may_use, schema.may_create) == (True, False)

    owners = app_connection.execute(
        text(
            "SELECT c.relname, pg_get_userbyid(c.relowner) AS owner "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'auth' AND c.relkind = 'r' ORDER BY c.relname"
        )
    ).all()
    assert [(row.relname, row.owner) for row in owners] == [
        ("membership_roles", migration_role),
        ("password_credentials", migration_role),
        ("password_reset_tokens", migration_role),
        ("preauth_csrf_states", migration_role),
        ("role_permissions", migration_role),
        ("roles", migration_role),
        ("security_events", migration_role),
        ("sessions", migration_role),
        ("tenant_memberships", migration_role),
        ("throttle_buckets", migration_role),
        ("users", migration_role),
    ]


def test_runtime_and_public_have_no_direct_auth_table_access(
    app_connection: Connection, application_role: str
) -> None:
    for table in TABLES:
        table_oid = app_connection.scalar(
            text(
                "SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'auth' AND c.relname = :table"
            ),
            {"table": table},
        )
        assert (
            app_connection.scalar(
                text(
                    "SELECT has_table_privilege(:role, :table_oid, "
                    "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')"
                ),
                {"role": application_role, "table_oid": table_oid},
            )
            is False
        )
        public_grants = app_connection.scalar(
            text(
                "SELECT count(*) FROM pg_class c CROSS JOIN LATERAL "
                "aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) acl "
                "WHERE c.oid = :table_oid AND acl.grantee = 0"
            ),
            {"table_oid": table_oid},
        )
        assert public_grants == 0


def test_identity_columns_constraints_and_indexes_exist(app_connection: Connection) -> None:
    user_columns = app_connection.execute(
        text(
            "SELECT a.attname AS column_name, a.attnotnull AS not_null, "
            "format_type(a.atttypid, a.atttypmod) AS data_type "
            "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'auth' AND c.relname = 'users' "
            "AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"
        )
    ).all()
    assert [row.column_name for row in user_columns] == [
        "id",
        "email",
        "normalized_email",
        "status",
        "email_verified_at",
        "security_version",
        "created_at",
        "updated_at",
    ]
    assert next(row for row in user_columns if row.column_name == "id").data_type == "uuid"
    normalized_email = next(row for row in user_columns if row.column_name == "normalized_email")
    assert normalized_email.not_null is True

    constraints = set(
        app_connection.execute(
            text(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class c ON c.oid = con.conrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'auth' "
                "AND c.relname IN ('users', 'tenant_memberships')"
            )
        ).scalars()
    )
    assert {
        "pk_users",
        "uq_users_normalized_email",
        "pk_tenant_memberships",
        "uq_tenant_memberships_user_tenant",
        "uq_tenant_memberships_id_user",
        "fk_tenant_memberships_user_id_users",
        "fk_tenant_memberships_tenant_id_tenants",
        "ck_tenant_memberships_lifecycle_timestamps",
    } <= constraints

    indexes = set(
        app_connection.execute(
            text(
                "SELECT i.relname FROM pg_index x "
                "JOIN pg_class t ON t.oid = x.indrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "JOIN pg_class i ON i.oid = x.indexrelid "
                "WHERE n.nspname = 'auth' AND t.relname = 'tenant_memberships'"
            )
        ).scalars()
    )
    assert {
        "ix_tenant_memberships_user_id_status",
        "ix_tenant_memberships_tenant_id_status",
    } <= indexes


def test_membership_is_the_only_approved_non_rls_tenant_id_table(
    app_connection: Connection,
) -> None:
    row = app_connection.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity, "
            "(SELECT count(*) FROM pg_policy WHERE polrelid = c.oid) AS policies "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'auth' AND c.relname = 'tenant_memberships'"
        )
    ).one()
    assert tuple(row) == (False, False, 0)


def test_auth_enums_match_the_domain_contract(app_connection: Connection) -> None:
    values = app_connection.execute(
        text(
            "SELECT t.typname, e.enumlabel FROM pg_type t "
            "JOIN pg_namespace n ON n.oid = t.typnamespace "
            "JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE n.nspname = 'auth' ORDER BY t.typname, e.enumsortorder"
        )
    ).all()
    assert values == [
        ("membership_status", "pending"),
        ("membership_status", "active"),
        ("membership_status", "suspended"),
        ("membership_status", "left"),
        ("role_status", "active"),
        ("role_status", "inactive"),
        ("user_status", "pending"),
        ("user_status", "active"),
        ("user_status", "suspended"),
        ("user_status", "archived"),
    ]
