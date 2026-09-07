"""Prove transaction-local isolation on one real reused PostgreSQL connection."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db import tenant_transaction as transaction_module
from app.tenancy.context import TenantContext
from tests.db.rls_probe import Probe, ProbeRow


@pytest.fixture
async def pooled_runtime_engine(
    settings: Settings, application_role: str, probe: Probe, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncEngine]:
    """Dispose this pool before the dependent probe fixture attempts its teardown."""
    engine = create_async_engine(
        settings.database_url, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    factory = async_sessionmaker(
        class_=transaction_module._session_factory.class_,
        **{**transaction_module._session_factory.kw, "bind": engine},
    )
    monkeypatch.setattr(transaction_module, "_session_factory", factory)
    try:
        async with engine.connect() as connection, connection.begin():
            assert await connection.scalar(text("SELECT current_user")) == application_role
            version = await connection.scalar(
                text("SELECT current_setting('server_version_num')::int")
            )
            assert version // 10000 == 17, "Pool isolation must be tested against PostgreSQL 17."
        yield engine
    finally:
        await engine.dispose()


class ServiceFailed(Exception):
    """A failure after service work, which must roll back the boundary transaction."""


@pytest.mark.parametrize("ending", ["commit", "rollback", "exception"])
async def test_next_pool_borrower_has_no_context_or_rows(
    pooled_runtime_engine: AsyncEngine, probe: Probe, ending: str
) -> None:
    """Database failure and application exception both exercise actual rollback."""
    pid: int | None = None
    exception_seen = False
    try:
        async with transaction_module.tenant_transaction(TenantContext(probe.tenant_a)) as work:
            pid = await work.scalar(text("SELECT pg_backend_pid()"))
            assert await work.scalar(text("SELECT app.current_tenant_id()")) == probe.tenant_a
            assert (await work.scalars(select(ProbeRow.id))).all() == [probe.row_a]
            if ending == "rollback":
                # A database error aborts the transaction; no public session
                # lifecycle handle is exposed to bypass the production boundary.
                await work.execute(text("SELECT 1 / 0"))
            elif ending == "exception":
                raise ServiceFailed
    except DBAPIError as exc:
        exception_seen = True
        assert ending == "rollback"
        assert getattr(exc.orig, "sqlstate", None) == "22012"
    except ServiceFailed:
        exception_seen = True
        assert ending == "exception"

    assert exception_seen is (ending != "commit")
    assert pid is not None
    async with pooled_runtime_engine.connect() as connection, connection.begin():
        # This intentionally bypasses the service resolver: PostgreSQL must
        # still deny rows when a direct borrower supplies no tenant context.
        assert await connection.scalar(text("SELECT pg_backend_pid()")) == pid
        assert await connection.scalar(text("SELECT app.current_tenant_id()")) is None
        assert await connection.scalar(text("SELECT count(*) FROM public.tenant_scoped_probe")) == 0


async def test_tenant_b_reuses_a_connection_without_seeing_tenant_a(
    pooled_runtime_engine: AsyncEngine, probe: Probe
) -> None:
    async with transaction_module.tenant_transaction(TenantContext(probe.tenant_a)) as work:
        pid_a = await work.scalar(text("SELECT pg_backend_pid()"))
        assert (await work.scalars(select(ProbeRow.id))).all() == [probe.row_a]

    async with transaction_module.tenant_transaction(TenantContext(probe.tenant_b)) as work:
        assert await work.scalar(text("SELECT pg_backend_pid()")) == pid_a
        assert await work.scalar(text("SELECT app.current_tenant_id()")) == probe.tenant_b
        assert (await work.scalars(select(ProbeRow.id))).all() == [probe.row_b]
        assert await work.scalar(select(ProbeRow.id).where(ProbeRow.id == probe.row_a)) is None

    async with pooled_runtime_engine.connect() as connection, connection.begin():
        assert await connection.scalar(text("SELECT pg_backend_pid()")) == pid_a
        assert await connection.scalar(text("SELECT app.current_tenant_id()")) is None
        assert await connection.scalar(text("SELECT count(*) FROM public.tenant_scoped_probe")) == 0
