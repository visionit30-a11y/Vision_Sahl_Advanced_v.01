"""A real RLS table, created and removed only by tests.

The ORM mapping has its own metadata and is never imported by the application
or Alembic. Setup is atomic; a failure rolls it back. Normal test failure still
runs the teardown, which drops only the table this fixture created.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import Engine, String, Table, Text, Uuid, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.models.tenant import TenantId, new_tenant_id


class ProbeBase(DeclarativeBase):
    pass


class ProbeRow(ProbeBase):
    __tablename__ = "tenant_scoped_probe"
    __table_args__ = ({"schema": "public"},)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


PROBE_TABLE = cast(Table, ProbeRow.__table__)


@dataclass(frozen=True)
class Probe:
    tenant_a: TenantId
    tenant_b: TenantId
    row_a: str = "a-row"
    row_b: str = "b-row"


@contextmanager
def provision_probe(engine: Engine, migration_role: str, application_role: str) -> Iterator[Probe]:
    """Seed before enabling FORCE; never give the owner a bypass policy."""
    state = Probe(new_tenant_id(), new_tenant_id())
    created = False
    try:
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT current_user")) == migration_role
            assert (
                connection.scalar(text("SELECT current_setting('server_version_num')::int"))
                // 10000
                == 17
            )
            assert (
                connection.scalar(text("SELECT to_regclass('public.tenant_scoped_probe')")) is None
            ), "A probe already exists; refuse to adopt or drop an unknown table."
            PROBE_TABLE.create(connection)
            connection.execute(
                PROBE_TABLE.insert(),
                [
                    {"id": state.row_a, "tenant_id": state.tenant_a, "payload": "tenant-a"},
                    {"id": state.row_b, "tenant_id": state.tenant_b, "payload": "tenant-b"},
                ],
            )
            connection.execute(
                text("ALTER TABLE public.tenant_scoped_probe ENABLE ROW LEVEL SECURITY")
            )
            connection.execute(
                text("ALTER TABLE public.tenant_scoped_probe FORCE ROW LEVEL SECURITY")
            )
            runtime = connection.dialect.identifier_preparer.quote(application_role)
            connection.execute(
                text(
                    "CREATE POLICY tenant_isolation ON public.tenant_scoped_probe "
                    f"FOR ALL TO {runtime} "
                    "USING (tenant_id = app.current_tenant_id()) "
                    "WITH CHECK (tenant_id = app.current_tenant_id())"
                )
            )
            connection.execute(
                text(f"REVOKE ALL ON TABLE public.tenant_scoped_probe FROM PUBLIC, {runtime}")
            )
            connection.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                    f"public.tenant_scoped_probe TO {runtime}"
                )
            )
        created = True
        yield state
    finally:
        if created:
            with engine.begin() as connection:
                # No CASCADE: unexpected dependencies are a failure, not silently removed.
                PROBE_TABLE.drop(connection)
                assert (
                    connection.scalar(text("SELECT to_regclass('public.tenant_scoped_probe')"))
                    is None
                )
                assert (
                    connection.scalar(text("SELECT to_regtype('public.tenant_scoped_probe')"))
                    is None
                )


@pytest.fixture
def probe(settings: Settings, migration_role: str, application_role: str) -> Iterator[Probe]:
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    try:
        with provision_probe(engine, migration_role, application_role) as state:
            yield state
    finally:
        engine.dispose()
