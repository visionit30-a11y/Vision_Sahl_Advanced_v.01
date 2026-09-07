"""Fixtures for tests that talk to a real PostgreSQL database.

Access-control proofs connect as the application role. The migration role is
used only for fixture DDL and rollback-only catalogue mutation checks; it must
never stand in for runtime access. The effective application role is checked
before a connection is handed to a test.

There is no SQLite here and nothing is mocked. These tests fail when the
database is unreachable rather than skipping, because a green suite that
quietly proved nothing is worse than a red one.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from tests.db.rls_probe import probe  # noqa: F401 - register the scoped fixture

DB_TESTS_DIRECTORY = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark everything in this package as needing a database.

    Marking here rather than in each module means a new test file cannot be
    added without the marker. The marker exists so a developer can run
    `pytest -m "not db"` while iterating; no quality gate uses that filter.
    """
    for item in items:
        if DB_TESTS_DIRECTORY in Path(str(item.path)).parents:
            item.add_marker(pytest.mark.db)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def application_role(settings: Settings) -> str:
    """The role the application connects with, read from the runtime URL."""
    role = make_url(settings.database_url).username
    assert role, "DATABASE_URL does not name a role."
    return role


@pytest.fixture(scope="session")
def migration_role(settings: Settings) -> str:
    """The role migrations connect with, read from the migration URL.

    Read, never written down: a hard coded role name in a test would still pass
    after someone renamed the real one.
    """
    role = make_url(settings.required_migration_database_url).username
    assert role, "MIGRATION_DATABASE_URL does not name a role."
    return role


@pytest.fixture(scope="session")
def application_engine(settings: Settings) -> Iterator[Engine]:
    """A synchronous engine on the runtime URL, for observing the database.

    NullPool because these tests care about what a fresh connection sees, and a
    pooled one would blur that.
    """
    engine = create_engine(settings.database_url, poolclass=NullPool, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def app_connection(application_engine: Engine, application_role: str) -> Iterator[Connection]:
    """A connection proven to be the application role's, rolled back afterwards."""
    with application_engine.connect() as connection:
        current_user = connection.execute(text("SELECT current_user")).scalar_one()
        assert current_user == application_role, (
            f"These tests must run as the application role {application_role!r}, "
            f"but this connection is {current_user!r}. Running them as any other role - "
            "the migration role above all - would prove nothing about isolation."
        )
        assert (
            connection.scalar(text("SELECT current_setting('server_version_num')::int")) // 10000
            == 17
        )
        yield connection
        connection.rollback()
