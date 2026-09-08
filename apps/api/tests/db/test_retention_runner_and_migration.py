"""Real disposable-PostgreSQL runner and reversible retention migration proofs.

The imported fixture requires APP_ENV=test, matching loopback sahl_ci URLs, and
an explicitly provisioned maintenance test login before any subprocess or DDL.
Run serially: the round-trip intentionally changes this isolated database head.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from tests.db.test_security_audit_retention import RetentionFixture
from tests.db.test_security_audit_retention import retention as retention

API_DIRECTORY = Path(__file__).resolve().parents[2]


def _environment(fixture: RetentionFixture, *, runtime: bool = False) -> dict[str, str]:
    capability = fixture.runtime if runtime else fixture.maintenance
    return {
        **os.environ,
        "APP_ENV": "test",
        "REDIS_ENABLED": "false",
        "DATABASE_URL": fixture.runtime.url.render_as_string(hide_password=False),
        "MIGRATION_DATABASE_URL": fixture.owner.url.render_as_string(hide_password=False),
        "SECURITY_MAINTENANCE_DATABASE_URL": capability.url.render_as_string(hide_password=False),
    }


def _process(arguments: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [sys.executable, "-m", *arguments],
            cwd=API_DIRECTORY,
            env=environment,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except Exception:  # noqa: BLE001 - never format captured process diagnostics
        pytest.fail("retention_proof_process_failed", pytrace=False)


def _runner(
    fixture: RetentionFixture, *arguments: str, runtime: bool = False
) -> tuple[int, dict[str, Any]]:
    process = _process(
        ["app.maintenance.security_audit_retention", "--execute", *arguments],
        _environment(fixture, runtime=runtime),
    )
    if process.stderr:
        pytest.fail("retention_runner_unexpected_stderr", pytrace=False)
    try:
        result = json.loads(process.stdout)
    except Exception:  # noqa: BLE001 - do not echo a malformed or sensitive response
        pytest.fail("retention_runner_invalid_output", pytrace=False)
    if (
        type(result) is not dict
        or set(result) != {"status", "deleted_count", "batches"}
        or result["status"] not in {"drained", "incomplete", "database_failure"}
        or type(result["deleted_count"]) is not int
        or type(result["batches"]) is not int
    ):
        pytest.fail("retention_runner_invalid_output", pytrace=False)
    return process.returncode, result


def _expected(status: str, count: int, batches: int) -> dict[str, Any]:
    return {"status": status, "deleted_count": count, "batches": batches}


def _migration(fixture: RetentionFixture, direction: str, target: str) -> None:
    result = _process(["alembic", direction, target], _environment(fixture))
    if result.returncode != 0:
        pytest.fail("retention_migration_command_failed", pytrace=False)


def _history(fixture: RetentionFixture) -> tuple[str, ...]:
    with fixture.owner.connect() as db:
        return tuple(
            db.scalars(
                text("SELECT to_jsonb(event)::text FROM auth.security_events event ORDER BY id")
            )
        )


def test_real_runner_commits_bounded_batches_then_resumes_and_is_idempotent(
    retention: RetentionFixture,
) -> None:
    retention.seed([timedelta(days=91)] * 5)
    assert _runner(retention, "--batch-size", "2", "--max-batches", "2") == (
        2,
        _expected("incomplete", 4, 2),
    )
    assert len(retention.remaining()) == 1
    assert [event.affected_count for event in retention.events()] == [2, 2]
    assert _runner(retention, "--batch-size", "2", "--max-batches", "2") == (
        0,
        _expected("drained", 1, 1),
    )
    assert retention.remaining() == set()
    assert [event.affected_count for event in retention.events()] == [2, 2, 1]
    assert _runner(retention) == (0, _expected("drained", 0, 1))
    assert len(retention.events()) == 3


def test_real_runner_locked_backlog_is_incomplete_and_emits_no_event(
    retention: RetentionFixture,
) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    with retention.owner.begin() as owner:
        owner.execute(
            text("SELECT id FROM auth.security_events WHERE id=:id FOR UPDATE"), {"id": identity}
        )
        assert _runner(retention) == (2, _expected("incomplete", 0, 1))
    assert retention.remaining() == {identity}
    assert retention.events() == []


def test_real_runner_runtime_credential_is_denied_with_closed_output(
    retention: RetentionFixture,
) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    assert _runner(retention, runtime=True) == (1, _expected("database_failure", 0, 0))
    assert retention.remaining() == {identity}
    assert retention.events() == []


def test_real_runner_mandatory_event_failure_rolls_back_the_batch(
    retention: RetentionFixture,
) -> None:
    [identity] = retention.seed([timedelta(days=91)])
    with retention.owner.begin() as owner:
        owner.execute(
            text(
                "ALTER TABLE auth.security_events ADD CONSTRAINT g4_runner_event_failure "
                "CHECK (event_type <> 'security_events_pruned') NOT VALID"
            )
        )
    try:
        assert _runner(retention) == (1, _expected("database_failure", 0, 0))
        assert retention.remaining() == {identity}
        assert retention.events() == []
    finally:
        with retention.owner.begin() as owner:
            owner.execute(
                text("ALTER TABLE auth.security_events DROP CONSTRAINT g4_runner_event_failure")
            )


def test_real_runner_second_batch_failure_preserves_only_the_first_commit(
    retention: RetentionFixture,
) -> None:
    retention.seed([timedelta(days=91)] * 3)
    with retention.owner.begin() as owner:
        owner.execute(
            text(
                "ALTER TABLE auth.security_events ADD CONSTRAINT g4_runner_second_batch_failure "
                "CHECK (event_type <> 'security_events_pruned' OR affected_count <> 1) NOT VALID"
            )
        )
    try:
        assert _runner(retention, "--batch-size", "2") == (1, _expected("database_failure", 2, 1))
        assert len(retention.remaining()) == 1
        assert [event.affected_count for event in retention.events()] == [2]
    finally:
        with retention.owner.begin() as owner:
            owner.execute(
                text(
                    "ALTER TABLE auth.security_events "
                    "DROP CONSTRAINT g4_runner_second_batch_failure"
                )
            )


def test_retention_migration_round_trip_preserves_history_and_capability_role(
    retention: RetentionFixture,
) -> None:
    retention.seed([timedelta(days=91), timedelta(days=1)])
    assert retention.prune() == (1, False)
    original_history = _history(retention)
    assert len(retention.events()) == 1
    with retention.owner.connect() as owner:
        capability = owner.execute(
            text(
                "SELECT oid,rolcanlogin,rolsuper,rolcreaterole,"
                "rolcreatedb,rolreplication,rolbypassrls "
                "FROM pg_roles WHERE rolname='sahl_security_maintenance'"
            )
        ).one()
    try:
        _migration(retention, "downgrade", "0015_security_event_wiring")
        assert _history(retention) == original_history
        with retention.owner.connect() as owner:
            assert owner.scalar(text("SELECT version_num FROM public.alembic_version")) == (
                "0015_security_event_wiring"
            )
            assert (
                owner.scalar(text("SELECT to_regprocedure('auth.prune_security_events(integer)')"))
                is None
            )
            assert (
                owner.scalar(text("SELECT to_regclass('auth.ix_security_events_retention')"))
                is None
            )
            assert (
                owner.execute(
                    text(
                        "SELECT oid,rolcanlogin,rolsuper,rolcreaterole,"
                        "rolcreatedb,rolreplication,rolbypassrls "
                        "FROM pg_roles WHERE rolname='sahl_security_maintenance'"
                    )
                ).one()
                == capability
            )
            assert owner.scalar(
                text(
                    "SELECT pg_has_role('sahl_maintenance_test',"
                    "'sahl_security_maintenance','MEMBER')"
                )
            )
    finally:
        # Always restore the head before fixture cleanup or another security test.
        _migration(retention, "upgrade", "head")
    assert _history(retention) == original_history
    with retention.owner.connect() as owner:
        assert owner.scalar(text("SELECT version_num FROM public.alembic_version")) == (
            "0016_security_audit_retention"
        )
        assert (
            owner.scalar(text("SELECT to_regprocedure('auth.prune_security_events(integer)')"))
            is not None
        )
        assert (
            owner.scalar(text("SELECT to_regclass('auth.ix_security_events_retention')"))
            is not None
        )
        assert (
            owner.execute(
                text(
                    "SELECT oid,rolcanlogin,rolsuper,rolcreaterole,"
                    "rolcreatedb,rolreplication,rolbypassrls "
                    "FROM pg_roles WHERE rolname='sahl_security_maintenance'"
                )
            ).one()
            == capability
        )
    assert retention.prune() == (0, False)
    assert _history(retention) == original_history
