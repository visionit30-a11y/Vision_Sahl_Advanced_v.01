"""Real PostgreSQL transaction lifetime, without a tenant table or pool leak fixture."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from structlog.contextvars import bound_contextvars, get_contextvars

from app.core.config import Settings
from app.db import tenant_transaction as transaction_module
from app.models.tenant import TenantId, new_tenant_id
from app.tenancy.context import TenantContext
from app.tenancy.explicit import ExplicitTenantResolver


@pytest.fixture
async def held_runtime_connection(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncConnection]:
    """Hold one connection explicitly to observe its next transaction, not its pool."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                actual = await connection.scalar(text("SELECT current_user"))
                assert actual == make_url(settings.database_url).username
            # Exercise the production session options, changing only the bind
            # so that the next transaction can inspect the same server connection.
            factory = async_sessionmaker(
                **{**transaction_module._session_factory.kw, "bind": connection}
            )
            monkeypatch.setattr(transaction_module, "_session_factory", factory)
            yield connection
    finally:
        await engine.dispose()


@pytest.mark.parametrize("fail", [False, True], ids=["commit", "rollback"])
async def test_context_lasts_exactly_one_transaction(
    held_runtime_connection: AsyncConnection, fail: bool
) -> None:
    connection = held_runtime_connection
    context = TenantContext(new_tenant_id())
    completed: list[str] = []
    event.listen(connection.sync_connection, "commit", lambda _conn: completed.append("commit"))
    event.listen(connection.sync_connection, "rollback", lambda _conn: completed.append("rollback"))
    captured: transaction_module.TenantTransaction | None = None
    pid: int | None = None

    class WorkFailed(Exception):
        pass

    with bound_contextvars(tenant_id="outer-log-value"):
        try:
            async with transaction_module.tenant_transaction(context) as session:
                captured = session
                assert connection.in_transaction()
                assert (
                    await session.scalar(text("SELECT app.current_tenant_id()"))
                    == context.tenant_id
                )
                pid = await session.scalar(text("SELECT pg_backend_pid()"))
                assert get_contextvars()["tenant_id"] == str(context.tenant_id)
                if fail:
                    raise WorkFailed
        except WorkFailed:
            assert fail
        assert get_contextvars()["tenant_id"] == "outer-log-value"
    assert completed == (["rollback"] if fail else ["commit"])
    assert not connection.in_transaction()
    assert captured is not None
    async with connection.begin():
        assert await connection.scalar(text("SELECT pg_backend_pid()")) == pid
        assert await connection.scalar(text("SELECT app.current_tenant_id()")) is None
    # Escaping a session reference cannot silently start a context-free query.
    with pytest.raises(InvalidRequestError):
        await captured.execute(text("SELECT 1"))


@pytest.mark.parametrize(
    "operation", ["commit", "rollback", "begin", "get_transaction", "connection"]
)
async def test_service_cannot_complete_the_boundary_transaction_early(
    held_runtime_connection: AsyncConnection, operation: str
) -> None:
    context = TenantContext(new_tenant_id())
    async with transaction_module.tenant_transaction(context) as session:
        assert not hasattr(session, operation)
        assert not hasattr(session, "sync_session")
        assert held_runtime_connection.in_transaction()
        result = await session.execute(text("SELECT app.current_tenant_id()"))
        assert result.scalar_one() == context.tenant_id
        values = await session.scalars(text("SELECT app.current_tenant_id()"))
        assert values.all() == [context.tenant_id]
    async with held_runtime_connection.begin():
        assert await held_runtime_connection.scalar(text("SELECT app.current_tenant_id()")) is None


async def test_explicit_identity_propagates_through_a_service_as_a_bound_parameter(
    held_runtime_connection: AsyncConnection,
) -> None:
    tenant_id = new_tenant_id()
    context = ExplicitTenantResolver(tenant_id).resolve()
    observed: list[tuple[str, object]] = []

    def observe(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if "set_config" in statement:
            observed.append((statement, parameters))

    event.listen(held_runtime_connection.sync_connection, "before_cursor_execute", observe)

    async def service(required_context: TenantContext) -> TenantId:
        async with transaction_module.tenant_transaction(required_context) as session:
            current = await session.scalar(text("SELECT app.current_tenant_id()"))
            assert current == required_context.tenant_id
            return cast(TenantId, current)

    assert await service(context) == tenant_id
    assert len(observed) == 1
    statement, parameters = observed[0]
    assert str(tenant_id) not in statement
    assert statement.endswith(", true)")
    assert isinstance(parameters, dict)
    assert parameters == {"tenant_id": str(tenant_id)}
