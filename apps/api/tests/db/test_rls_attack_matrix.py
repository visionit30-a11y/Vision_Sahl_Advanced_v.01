"""A1-A12: PostgreSQL RLS attacks using the actual application role.

Direct SQL and ORM statements intentionally have no tenant predicates. The
fixture supplies a real, temporary-lifetime table with the production policy
contract. Each connection closes before fixture teardown can drop that table.
A13 (connection reuse and transaction lifetime) is covered separately.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from psycopg import Error as PsycopgError
from sqlalchemy import Connection, Engine, delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.tenant import TenantId, new_tenant_id
from tests.db.rls_probe import Probe, ProbeRow

_SET_CONTEXT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")
_INSERT_ROW = text(
    "INSERT INTO public.tenant_scoped_probe (id, tenant_id, payload) "
    "VALUES (:id, :tenant_id, :payload)"
)


@contextmanager
def runtime_connection(engine: Engine, role: str) -> Iterator[Connection]:
    """Prove the effective role and release all locks before probe teardown."""
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT current_user")) == role
        yield connection


def bind_context(connection: Connection, value: str) -> None:
    assert connection.in_transaction()
    connection.execute(_SET_CONTEXT, {"tenant_id": value})


def assert_rls_denial(failure: pytest.ExceptionInfo[DBAPIError]) -> None:
    """A forbidden write must fail at PostgreSQL, not disappear from a later read."""
    assert isinstance(failure.value.orig, PsycopgError)
    assert failure.value.orig.sqlstate == "42501"


def assert_insert_denied(connection: Connection, tenant_id: TenantId) -> None:
    with pytest.raises(DBAPIError) as failure, connection.begin_nested():
        connection.execute(
            _INSERT_ROW,
            {"id": "forbidden-row", "tenant_id": tenant_id, "payload": "must-not-be-written"},
        )
    assert_rls_denial(failure)


@contextmanager
def runtime_session(engine: Engine, role: str, tenant_id: TenantId) -> Iterator[Session]:
    with Session(engine, autobegin=False) as session, session.begin():
        assert session.scalar(text("SELECT current_user")) == role
        session.execute(_SET_CONTEXT, {"tenant_id": str(tenant_id)})
        yield session


def test_a1_own_tenant_read_and_positive_crud(
    probe: Probe, application_engine: Engine, application_role: str
) -> None:
    """Own-tenant success proves that denying attacks is not an always-false policy."""
    with runtime_connection(application_engine, application_role) as connection:
        bind_context(connection, str(probe.tenant_a))
        rows = connection.execute(
            text("SELECT id, tenant_id FROM public.tenant_scoped_probe")
        ).all()
        assert [tuple(row) for row in rows] == [(probe.row_a, probe.tenant_a)]

        connection.execute(
            _INSERT_ROW,
            {"id": "owned-new", "tenant_id": probe.tenant_a, "payload": "created"},
        )
        assert set(connection.scalars(text("SELECT id FROM public.tenant_scoped_probe"))) == {
            probe.row_a,
            "owned-new",
        }
        changed = connection.execute(
            text(
                "UPDATE public.tenant_scoped_probe SET payload = :payload "
                "WHERE id = :id RETURNING payload"
            ),
            {"id": "owned-new", "payload": "updated"},
        ).scalar_one()
        assert changed == "updated"
        deleted = connection.execute(
            text("DELETE FROM public.tenant_scoped_probe WHERE id = :id"), {"id": "owned-new"}
        )
        assert deleted.rowcount == 1
        assert connection.scalars(text("SELECT id FROM public.tenant_scoped_probe")).all() == [
            probe.row_a
        ]


@pytest.mark.parametrize("as_a", [True, False], ids=["A2-A-cannot-read-B", "A3-B-cannot-read-A"])
def test_a2_a3_known_foreign_id_is_invisible(
    probe: Probe, application_engine: Engine, application_role: str, as_a: bool
) -> None:
    tenant = probe.tenant_a if as_a else probe.tenant_b
    own_row = probe.row_a if as_a else probe.row_b
    foreign_row = probe.row_b if as_a else probe.row_a
    with runtime_connection(application_engine, application_role) as connection:
        bind_context(connection, str(tenant))
        assert connection.scalars(text("SELECT id FROM public.tenant_scoped_probe")).all() == [
            own_row
        ]
        assert (
            connection.execute(
                text("SELECT * FROM public.tenant_scoped_probe WHERE id = :id"), {"id": foreign_row}
            ).all()
            == []
        )


@pytest.mark.parametrize("operation", ["update", "delete"], ids=["A4-update-B", "A5-delete-B"])
def test_a4_a5_foreign_update_and_delete_affect_zero_rows(
    probe: Probe, application_engine: Engine, application_role: str, operation: str
) -> None:
    statements = {
        "update": text("UPDATE public.tenant_scoped_probe SET payload = 'attacked' WHERE id = :id"),
        "delete": text("DELETE FROM public.tenant_scoped_probe WHERE id = :id"),
    }
    with runtime_connection(application_engine, application_role) as connection:
        bind_context(connection, str(probe.tenant_b))
        original = connection.scalar(text("SELECT payload FROM public.tenant_scoped_probe"))
        bind_context(connection, str(probe.tenant_a))
        result = connection.execute(statements[operation], {"id": probe.row_b})
        assert result.rowcount == 0
        bind_context(connection, str(probe.tenant_b))
        assert connection.scalar(text("SELECT payload FROM public.tenant_scoped_probe")) == original
        assert connection.scalars(text("SELECT id FROM public.tenant_scoped_probe")).all() == [
            probe.row_b
        ]


def test_a6_foreign_insert_is_rejected_with_sqlstate_42501(
    probe: Probe, application_engine: Engine, application_role: str
) -> None:
    with runtime_connection(application_engine, application_role) as connection:
        bind_context(connection, str(probe.tenant_a))
        assert_insert_denied(connection, probe.tenant_b)
        bind_context(connection, str(probe.tenant_b))
        assert connection.scalars(text("SELECT id FROM public.tenant_scoped_probe")).all() == [
            probe.row_b
        ]


def test_a7_moving_an_owned_row_to_b_is_rejected_with_sqlstate_42501(
    probe: Probe, application_engine: Engine, application_role: str
) -> None:
    with runtime_connection(application_engine, application_role) as connection:
        bind_context(connection, str(probe.tenant_a))
        with pytest.raises(DBAPIError) as failure, connection.begin_nested():
            connection.execute(
                text("UPDATE public.tenant_scoped_probe SET tenant_id = :tenant_id WHERE id = :id"),
                {"tenant_id": probe.tenant_b, "id": probe.row_a},
            )
        assert_rls_denial(failure)
        assert connection.execute(
            text("SELECT id, tenant_id FROM public.tenant_scoped_probe")
        ).one() == (probe.row_a, probe.tenant_a)


def test_a8_missing_context_reads_nothing_and_cannot_insert(
    probe: Probe, application_engine: Engine, application_role: str
) -> None:
    with runtime_connection(application_engine, application_role) as connection:
        assert connection.scalar(text("SELECT app.current_tenant_id()")) is None
        assert connection.execute(text("SELECT * FROM public.tenant_scoped_probe")).all() == []
        assert_insert_denied(connection, probe.tenant_a)


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_a9_missing_context_cannot_update_or_delete_any_row(
    probe: Probe, application_engine: Engine, application_role: str, operation: str
) -> None:
    statements = {
        "update": text("UPDATE public.tenant_scoped_probe SET payload = 'attacked'"),
        "delete": text("DELETE FROM public.tenant_scoped_probe"),
    }
    with runtime_connection(application_engine, application_role) as connection:
        assert connection.scalar(text("SELECT app.current_tenant_id()")) is None
        assert connection.execute(statements[operation]).rowcount == 0
        bind_context(connection, str(probe.tenant_a))
        assert connection.scalars(text("SELECT id FROM public.tenant_scoped_probe")).all() == [
            probe.row_a
        ]
        bind_context(connection, str(probe.tenant_b))
        assert connection.scalars(text("SELECT id FROM public.tenant_scoped_probe")).all() == [
            probe.row_b
        ]


@pytest.mark.parametrize("context_kind", ["empty", "malformed", "unknown-uuid"])
def test_a10_invalid_or_unknown_context_cannot_access_existing_tenants(
    probe: Probe, application_engine: Engine, application_role: str, context_kind: str
) -> None:
    values = {"empty": "", "malformed": "not-a-uuid", "unknown-uuid": str(new_tenant_id())}
    with runtime_connection(application_engine, application_role) as connection:
        bind_context(connection, values[context_kind])
        current = connection.scalar(text("SELECT app.current_tenant_id()"))
        if context_kind == "unknown-uuid":
            # The function does no lookup: a valid unknown ID simply matches no row.
            assert str(current) == values[context_kind]
            assert current not in {probe.tenant_a, probe.tenant_b}
        else:
            assert current is None
        assert connection.execute(text("SELECT * FROM public.tenant_scoped_probe")).all() == []
        assert_insert_denied(connection, probe.tenant_a)


def test_a11_raw_sql_without_any_where_clause_still_isolates_all_operations(
    probe: Probe, application_engine: Engine, application_role: str
) -> None:
    with runtime_connection(application_engine, application_role) as connection:
        bind_context(connection, str(probe.tenant_a))
        updated = (
            connection.execute(
                text("UPDATE public.tenant_scoped_probe SET payload = 'owned-update' RETURNING id")
            )
            .scalars()
            .all()
        )
        assert updated == [probe.row_a]
        deleted = (
            connection.execute(text("DELETE FROM public.tenant_scoped_probe RETURNING id"))
            .scalars()
            .all()
        )
        assert deleted == [probe.row_a]
        bind_context(connection, str(probe.tenant_b))
        assert connection.scalars(text("SELECT id FROM public.tenant_scoped_probe")).all() == [
            probe.row_b
        ]


@pytest.mark.parametrize("as_a", [True, False], ids=["A-cannot-read-B", "B-cannot-read-A"])
def test_a12_orm_reads_are_isolated_without_tenant_filters(
    probe: Probe, application_engine: Engine, application_role: str, as_a: bool
) -> None:
    tenant = probe.tenant_a if as_a else probe.tenant_b
    own_row = probe.row_a if as_a else probe.row_b
    foreign_row = probe.row_b if as_a else probe.row_a
    with runtime_session(application_engine, application_role, tenant) as session:
        assert [row.id for row in session.scalars(select(ProbeRow)).all()] == [own_row]
        assert session.get(ProbeRow, foreign_row) is None


def test_a12_orm_positive_crud_works_for_the_current_tenant(
    probe: Probe, application_engine: Engine, application_role: str
) -> None:
    with runtime_session(application_engine, application_role, probe.tenant_a) as session:
        owned = ProbeRow(id="orm-owned", tenant_id=probe.tenant_a, payload="created")
        session.add(owned)
        session.flush()
        session.expire_all()
        assert {row.id for row in session.scalars(select(ProbeRow)).all()} == {
            probe.row_a,
            "orm-owned",
        }
        assert owned.payload == "created"
        owned.payload = "updated"
        session.flush()
        session.expire(owned)
        assert owned.payload == "updated"
        session.delete(owned)
        session.flush()
        assert [row.id for row in session.scalars(select(ProbeRow)).all()] == [probe.row_a]


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_a12_orm_foreign_update_and_delete_affect_zero_rows(
    probe: Probe, application_engine: Engine, application_role: str, operation: str
) -> None:
    statement = (
        update(ProbeRow).where(ProbeRow.id == probe.row_b).values(payload="attacked")
        if operation == "update"
        else delete(ProbeRow).where(ProbeRow.id == probe.row_b)
    )
    with runtime_session(application_engine, application_role, probe.tenant_a) as session:
        affected = session.scalars(statement.returning(ProbeRow.id)).all()
        assert affected == []
    with runtime_session(application_engine, application_role, probe.tenant_b) as session:
        assert [row.id for row in session.scalars(select(ProbeRow)).all()] == [probe.row_b]
        assert session.scalars(select(ProbeRow.payload)).one() != "attacked"


@pytest.mark.parametrize("operation", ["insert-B", "move-A-to-B"])
def test_a12_orm_with_check_rejects_foreign_writes_with_sqlstate_42501(
    probe: Probe, application_engine: Engine, application_role: str, operation: str
) -> None:
    with runtime_session(application_engine, application_role, probe.tenant_a) as session:
        with pytest.raises(DBAPIError) as failure, session.begin_nested():
            if operation == "insert-B":
                session.add(
                    ProbeRow(id="orm-forbidden", tenant_id=probe.tenant_b, payload="attacked")
                )
            else:
                owned = session.get(ProbeRow, probe.row_a)
                assert owned is not None
                owned.tenant_id = probe.tenant_b
            session.flush()
        assert_rls_denial(failure)
        assert [(row.id, row.tenant_id) for row in session.scalars(select(ProbeRow)).all()] == [
            (probe.row_a, probe.tenant_a)
        ]
    with runtime_session(application_engine, application_role, probe.tenant_b) as session:
        assert [row.id for row in session.scalars(select(ProbeRow)).all()] == [probe.row_b]


@pytest.mark.parametrize("context_kind", ["missing", "empty", "malformed", "unknown-uuid"])
def test_a8_a9_a10_orm_without_matching_context_fails_closed_for_all_crud(
    probe: Probe, application_engine: Engine, application_role: str, context_kind: str
) -> None:
    values = {"empty": "", "malformed": "not-a-uuid", "unknown-uuid": str(new_tenant_id())}
    with Session(application_engine, autobegin=False) as session, session.begin():
        assert session.scalar(text("SELECT current_user")) == application_role
        if context_kind != "missing":
            session.execute(_SET_CONTEXT, {"tenant_id": values[context_kind]})
        current = session.scalar(text("SELECT app.current_tenant_id()"))
        if context_kind == "unknown-uuid":
            # Valid UUIDs pass through without a tenant-registry lookup.
            assert str(current) == values[context_kind]
            assert current not in {probe.tenant_a, probe.tenant_b}
        else:
            assert current is None

        assert session.scalars(select(ProbeRow)).all() == []
        updated = session.scalars(
            update(ProbeRow).values(payload="attacked").returning(ProbeRow.id)
        ).all()
        assert updated == []
        deleted = session.scalars(delete(ProbeRow).returning(ProbeRow.id)).all()
        assert deleted == []
        with pytest.raises(DBAPIError) as failure, session.begin_nested():
            session.add(ProbeRow(id="orm-no-context", tenant_id=probe.tenant_a, payload="attacked"))
            session.flush()
        assert_rls_denial(failure)
        assert session.scalars(select(ProbeRow)).all() == []
