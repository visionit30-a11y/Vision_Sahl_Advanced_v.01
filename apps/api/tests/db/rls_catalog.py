"""Live catalogue contract for every user table carrying a tenant_id column."""

from __future__ import annotations

import re

from sqlalchemy import Connection, text


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

    No production table currently needs this contract. The probe tests exercise
    the same discovery with a nonempty catalogue and deliberate bad metadata.
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
