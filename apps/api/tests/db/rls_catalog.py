"""Live catalogue contract for every user table carrying a tenant_id column."""

from __future__ import annotations

import re

from sqlalchemy import Connection, text

IDENTITY_SECURITY_TENANT_TABLES = frozenset({"auth.tenant_memberships"})
MEMBERSHIP_COLUMNS = frozenset(
    {
        "id",
        "user_id",
        "tenant_id",
        "status",
        "joined_at",
        "left_at",
        "version",
        "created_at",
        "updated_at",
    }
)


def normalized_predicate(value: str | None) -> str:
    """Ignore only whitespace and balanced outer grouping; preserve function calls."""
    expression = re.sub(r"\s+", "", value or "")
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        outer_end = -1
        for index, character in enumerate(expression):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            if depth == 0:
                outer_end = index
                break
        if outer_end != len(expression) - 1:
            break
        expression = expression[1:-1]
    return expression


def assert_tenant_catalog(
    connection: Connection, *, application_role: str, migration_role: str
) -> list[str]:
    """Discover tenant ownership structurally and reject incomplete RLS contracts.

    The membership catalogue has one approved identity-security exception. It
    remains discovered and is checked against a narrower no-direct-access
    contract; every other table follows the Phase 2A tenant-owned contract.
    """
    version = connection.scalar(text("SELECT current_setting('server_version_num')::int"))
    assert version // 10000 == 17, "The security catalogue gate requires PostgreSQL 17."
    application_oid = connection.execute(
        text("SELECT oid FROM pg_roles WHERE rolname = :role"),
        {"role": application_role},
    ).scalar_one()
    tables = connection.execute(
        text(
            "SELECT c.oid, n.nspname AS schema_name, c.relname, "
            "pg_get_userbyid(c.relowner) AS owner, "
            "c.relrowsecurity, c.relforcerowsecurity, a.attnotnull, "
            "a.atttypid = 'uuid'::regtype AS uuid_column "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = c.oid "
            "AND a.attname = 'tenant_id' AND a.attnum > 0 AND NOT a.attisdropped "
            "WHERE c.relkind IN ('r', 'p') "
            "AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema' "
            "ORDER BY n.nspname, c.relname"
        )
    ).all()
    failures: list[str] = []
    discovered: list[str] = []
    expected = normalized_predicate("tenant_id = app.current_tenant_id()")
    for table in tables:
        name = f"{table.schema_name}.{table.relname}"
        discovered.append(name)
        if table.owner != migration_role:
            failures.append(f"{name}: owner must be the migration role")
        if not table.uuid_column or not table.attnotnull:
            failures.append(f"{name}: tenant_id must be UUID NOT NULL")
        if name in IDENTITY_SECURITY_TENANT_TABLES:
            _check_membership_exception(
                connection,
                table_oid=table.oid,
                table_name=name,
                application_role=application_role,
                failures=failures,
            )
            continue
        if not table.relrowsecurity:
            failures.append(f"{name}: ENABLE ROW LEVEL SECURITY is required")
        if not table.relforcerowsecurity:
            failures.append(f"{name}: FORCE ROW LEVEL SECURITY is required")
        policies = connection.execute(
            text(
                "SELECT polname, polcmd, polpermissive, polroles, "
                "pg_get_expr(polqual, polrelid) AS using_expression, "
                "pg_get_expr(polwithcheck, polrelid) AS check_expression "
                "FROM pg_policy WHERE polrelid = :table_oid"
            ),
            {"table_oid": table.oid},
        ).all()
        if len(policies) != 1:
            failures.append(f"{name}: exactly one isolation policy is required")
            continue
        policy = policies[0]
        if policy.polcmd != "*" or not policy.polpermissive:
            failures.append(f"{name}: the isolation policy must cover ALL commands")
        if list(policy.polroles) != [application_oid]:
            failures.append(f"{name}: the policy must target only the application role")
        if normalized_predicate(policy.using_expression) != expected:
            failures.append(f"{name}: USING must be the tenant identity equality")
        if normalized_predicate(policy.check_expression) != expected:
            failures.append(f"{name}: explicit WITH CHECK must be the tenant identity equality")
    assert not failures, "\n".join(failures)
    return discovered


def _check_membership_exception(
    connection: Connection,
    *,
    table_oid: int,
    table_name: str,
    application_role: str,
    failures: list[str],
) -> None:
    """Enforce ADR-0018 without turning auth into an exclusion namespace."""
    metadata = connection.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity, "
            "(SELECT count(*) FROM pg_policy WHERE polrelid = c.oid) AS policy_count "
            "FROM pg_class c WHERE c.oid = :table_oid"
        ),
        {"table_oid": table_oid},
    ).one()
    if metadata.relrowsecurity or metadata.relforcerowsecurity or metadata.policy_count:
        failures.append(f"{table_name}: identity-security exception must not declare tenant RLS")

    columns = frozenset(
        connection.execute(
            text(
                "SELECT attname FROM pg_attribute WHERE attrelid = :table_oid "
                "AND attnum > 0 AND NOT attisdropped"
            ),
            {"table_oid": table_oid},
        ).scalars()
    )
    if columns != MEMBERSHIP_COLUMNS:
        failures.append(f"{table_name}: columns must match the approved identity contract")

    tenant_fk_count = connection.scalar(
        text(
            "SELECT count(*) FROM pg_constraint con "
            "WHERE con.conrelid = :table_oid AND con.contype = 'f' "
            "AND con.confrelid = 'public.tenants'::regclass "
            "AND con.conkey = ARRAY[(SELECT attnum::smallint FROM pg_attribute "
            "WHERE attrelid = :table_oid AND attname = 'tenant_id')] "
            "AND con.confkey = ARRAY[(SELECT attnum::smallint FROM pg_attribute "
            "WHERE attrelid = 'public.tenants'::regclass AND attname = 'id')]"
        ),
        {"table_oid": table_oid},
    )
    if tenant_fk_count != 1:
        failures.append(f"{table_name}: tenant_id must reference public.tenants(id)")

    runtime_access = connection.scalar(
        text(
            "SELECT has_table_privilege(:role, :table_oid, "
            "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') OR "
            "EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = :table_oid "
            "AND a.attnum > 0 AND NOT a.attisdropped AND ("
            "has_column_privilege(:role, :table_oid, a.attnum, 'SELECT') OR "
            "has_column_privilege(:role, :table_oid, a.attnum, 'INSERT') OR "
            "has_column_privilege(:role, :table_oid, a.attnum, 'UPDATE') OR "
            "has_column_privilege(:role, :table_oid, a.attnum, 'REFERENCES')))"
        ),
        {"role": application_role, "table_oid": table_oid},
    )
    public_access = connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_class c CROSS JOIN LATERAL "
            "aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) acl "
            "WHERE c.oid = :table_oid AND acl.grantee = 0) OR "
            "EXISTS (SELECT 1 FROM pg_attribute a CROSS JOIN LATERAL "
            "aclexplode(a.attacl) acl WHERE a.attrelid = :table_oid "
            "AND a.attnum > 0 AND NOT a.attisdropped AND acl.grantee = 0)"
        ),
        {"table_oid": table_oid},
    )
    if runtime_access:
        failures.append(f"{table_name}: runtime must have no direct data privileges")
    if public_access:
        failures.append(f"{table_name}: PUBLIC must have no direct data privileges")
