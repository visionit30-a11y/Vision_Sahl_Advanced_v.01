"""Runtime cannot weaken RLS, replace its policies, drop its table or truncate it."""

from __future__ import annotations

import pytest
from psycopg import Error as PsycopgError
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.db.rls_probe import Probe

_POLICY_METADATA = text(
    "SELECT c.oid, c.relowner, c.relrowsecurity, c.relforcerowsecurity, "
    "p.oid AS policy_oid, p.polname, p.polcmd, p.polpermissive, p.polroles, "
    "pg_get_expr(p.polqual, p.polrelid) AS using_expression, "
    "pg_get_expr(p.polwithcheck, p.polrelid) AS check_expression "
    "FROM pg_class c JOIN pg_policy p ON p.polrelid = c.oid "
    "WHERE c.oid = 'public.tenant_scoped_probe'::regclass"
)


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE public.tenant_scoped_probe DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.tenant_scoped_probe NO FORCE ROW LEVEL SECURITY",
        "DROP TABLE public.tenant_scoped_probe",
        "CREATE POLICY runtime_bypass ON public.tenant_scoped_probe "
        "FOR ALL USING (true) WITH CHECK (true)",
        "ALTER POLICY tenant_isolation ON public.tenant_scoped_probe "
        "USING (true) WITH CHECK (true)",
        "DROP POLICY tenant_isolation ON public.tenant_scoped_probe",
        "TRUNCATE TABLE public.tenant_scoped_probe",
    ],
    ids=[
        "disable-rls",
        "remove-force",
        "drop-table",
        "create-policy",
        "alter-policy",
        "drop-policy",
        "truncate",
    ],
)
def test_runtime_ddl_is_denied_without_changing_probe_policy_or_rows(
    probe: Probe, application_engine: Engine, application_role: str, statement: str
) -> None:
    # An unexpected successful DDL statement still rolls back when pytest.raises
    # fails. The connection closes before the fixture drops its own probe.
    with application_engine.begin() as connection:
        assert connection.scalar(text("SELECT current_user")) == application_role
        before = connection.execute(_POLICY_METADATA).one()
        assert before.relrowsecurity is True
        assert before.relforcerowsecurity is True
        assert before.polname == "tenant_isolation"
        assert before.polcmd == "*"
        assert before.using_expression is not None
        assert before.check_expression is not None

        with pytest.raises(DBAPIError) as failure, connection.begin_nested():
            connection.execute(text(statement))
        assert isinstance(failure.value.orig, PsycopgError)
        assert failure.value.orig.sqlstate == "42501"

        # Reading pg_policy again proves the rejected command left the actual
        # policy (including both predicates and target roles) untouched.
        after = connection.execute(_POLICY_METADATA).one()
        assert tuple(after) == tuple(before)
        for tenant_id, row_id in ((probe.tenant_a, probe.row_a), (probe.tenant_b, probe.row_b)):
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            assert connection.scalars(text("SELECT id FROM public.tenant_scoped_probe")).all() == [
                row_id
            ]
