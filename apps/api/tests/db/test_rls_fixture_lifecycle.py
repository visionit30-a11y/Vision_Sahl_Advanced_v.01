"""The RLS fixture removes all of its objects even when test work raises."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.base import Base
from tests.db.rls_probe import provision_probe


def schema_objects(engine: Engine) -> set[tuple[str, str, str]]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT 'relation', n.nspname, c.relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname IN ('public','app') "
                    "UNION ALL SELECT 'type', n.nspname, t.typname FROM pg_type t "
                    "JOIN pg_namespace n ON n.oid=t.typnamespace "
                    "WHERE n.nspname IN ('public','app') "
                    "UNION ALL SELECT 'function', n.nspname, p.proname FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname IN ('public','app') "
                    "UNION ALL SELECT 'policy', schemaname, policyname FROM pg_policies "
                    "WHERE schemaname IN ('public','app')"
                )
            )
            .tuples()
            .all()
        )


@pytest.mark.parametrize("fail", [False, True], ids=["success", "exception"])
def test_probe_leaves_the_schema_exactly_as_it_was(
    settings: Settings, migration_role: str, application_role: str, fail: bool
) -> None:
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)

    class ExpectedFailure(Exception):
        pass

    try:
        before = schema_objects(engine)
        try:
            with provision_probe(engine, migration_role, application_role):
                during = schema_objects(engine)
                assert ("relation", "public", "tenant_scoped_probe") in during
                assert ("policy", "public", "tenant_isolation") in during
                if not fail:
                    check = subprocess.run(
                        [sys.executable, "-B", "-m", "tests.db.verify_clean_database"],
                        cwd=Path(__file__).resolve().parents[2],
                        capture_output=True,
                        text=True,
                        timeout=20,
                        check=False,
                    )
                    assert check.returncode == 1, check.stdout + check.stderr
                    assert "FAIL: post-test database guard:" in check.stdout
                if fail:
                    raise ExpectedFailure
        except ExpectedFailure:
            assert fail
        assert schema_objects(engine) == before
        assert all("tenant_scoped_probe" not in name for name in Base.metadata.tables)
    finally:
        engine.dispose()
