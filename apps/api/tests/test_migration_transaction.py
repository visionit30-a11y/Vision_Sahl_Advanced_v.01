"""Alembic owns the transaction containing its role check and migration body.

These PostgreSQL tests execute the real env.py and Alembic transaction context.
Only the migration body is replaced, with SELECT 1: no schema or revision is
changed. The success case must commit, catching the pre-configure SELECT that
used to make Alembic leave an implicit transaction to roll back on close.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest
import sqlalchemy
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, create_engine, event, text
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"


@pytest.mark.db
@pytest.mark.parametrize("use_application_role", [False, True], ids=["migrator", "application"])
def test_role_validation_uses_alembics_transaction(
    monkeypatch: pytest.MonkeyPatch, use_application_role: bool
) -> None:
    settings = get_settings()
    url = (
        settings.database_url if use_application_role else settings.required_migration_database_url
    )
    engine = create_engine(url, poolclass=NullPool)
    transactions: list[str] = []
    migration_calls: list[bool] = []

    def record_begin(_connection: Connection) -> None:
        transactions.append("begin")

    def record_commit(_connection: Connection) -> None:
        transactions.append("commit")

    def record_rollback(_connection: Connection) -> None:
        transactions.append("rollback")

    event.listen(engine, "begin", record_begin)
    event.listen(engine, "commit", record_commit)
    event.listen(engine, "rollback", record_rollback)
    monkeypatch.setattr(sqlalchemy, "engine_from_config", lambda *_args, **_kwargs: engine)

    try:
        with EnvironmentContext(Config(), ScriptDirectory(str(MIGRATIONS))) as environment:

            def read_only_migration_body() -> None:
                migration_calls.append(True)
                connection = environment.get_context().bind
                assert connection is not None
                assert connection.in_transaction()
                assert connection.execute(text("SELECT 1")).scalar_one() == 1

            monkeypatch.setattr(environment, "run_migrations", read_only_migration_body)
            if use_application_role:
                with pytest.raises(RuntimeError, match="role the application runs with"):
                    runpy.run_path(str(MIGRATIONS / "env.py"))
            else:
                runpy.run_path(str(MIGRATIONS / "env.py"))
    finally:
        engine.dispose()

    if use_application_role:
        assert migration_calls == []
        assert transactions == ["begin", "rollback"]
    else:
        assert migration_calls == [True]
        assert transactions == ["begin", "commit"]
