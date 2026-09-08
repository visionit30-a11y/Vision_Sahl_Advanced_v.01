"""Bounded retention CLI contracts without PostgreSQL or application settings."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import URL
from sqlalchemy.pool import NullPool

from app.maintenance import security_audit_retention as cli


@dataclass
class _Engine:
    responses: list[list[dict[str, Any]] | Exception]
    commit_failure: int | None = None
    disposal_failure: bool = False
    trace: list[str] = field(default_factory=list)
    parameters: list[dict[str, int]] = field(default_factory=list)
    marker: str = field(default_factory=lambda: uuid.uuid4().hex)
    current: int = -1

    @contextmanager
    def begin(self) -> Iterator[_Engine]:
        self.current += 1
        self.trace.append("begin")
        try:
            yield self
            if self.current == self.commit_failure:
                raise RuntimeError(self.marker)
        except BaseException:
            self.trace.append("rollback")
            raise
        else:
            self.trace.append("commit")

    def execute(self, statement: Any, parameters: dict[str, int]) -> _Engine:
        assert str(statement) == (
            "SELECT deleted_count, remaining_expired FROM auth.prune_security_events(:batch_size)"
        )
        self.trace.append("execute")
        self.parameters.append(parameters)
        logging.getLogger("sqlalchemy.engine").error("%s", {"password": self.marker})
        response = self.responses[self.current]
        if isinstance(response, Exception):
            raise response
        return self

    def mappings(self) -> _Engine:
        return self

    def all(self) -> list[dict[str, Any]]:
        response = self.responses[self.current]
        assert not isinstance(response, Exception)
        return response

    def dispose(self) -> None:
        self.trace.append("dispose")
        if self.disposal_failure:
            raise RuntimeError(self.marker)


def _row(count: Any = 0, remaining: Any = False) -> list[dict[str, Any]]:
    return [{"deleted_count": count, "remaining_expired": remaining}]


@pytest.fixture
def environment() -> dict[str, str]:
    url = URL.create(
        "postgresql+psycopg",
        username="fixture_maintenance",
        password=uuid.uuid4().hex,
        host="127.0.0.1",
        port=5434,
        database="fixture_database",
    )
    return {"SECURITY_MAINTENANCE_DATABASE_URL": url.render_as_string(hide_password=False)}


def _install(monkeypatch: pytest.MonkeyPatch, engine: _Engine) -> None:
    monkeypatch.setattr(cli, "_make_engine", lambda _url: engine)


def _assert_output(
    capsys: pytest.CaptureFixture[str], status: str, count: int, batches: int
) -> None:
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "status": status,
        "deleted_count": count,
        "batches": batches,
    }


@pytest.mark.parametrize("args", [[], ["--batch-size", "1"], ["--max-batches", "1"]])
def test_missing_execute_never_constructs_engine(
    args: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    monkeypatch.setattr(cli, "_make_engine", lambda _url: pytest.fail("Unexpected database access"))
    assert cli.main(args, environ=environment) == 1
    _assert_output(capsys, "invalid_configuration", 0, 0)


@pytest.mark.parametrize("fallback", ["DATABASE_URL", "MIGRATION_DATABASE_URL", "REDIS_URL"])
def test_missing_dedicated_env_never_uses_fallback(
    fallback: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
    tmp_path: Path,
) -> None:
    dsn = environment["SECURITY_MAINTENANCE_DATABASE_URL"]
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"SECURITY_MAINTENANCE_DATABASE_URL={dsn}\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_make_engine", lambda _url: pytest.fail("Unexpected database access"))
    assert cli.main(["--execute"], environ={fallback: dsn}) == 1
    _assert_output(capsys, "invalid_configuration", 0, 0)


@pytest.mark.parametrize(
    "args",
    [
        ["--batch-size", "0"],
        ["--batch-size", "1001"],
        ["--batch-size", "-1"],
        ["--max-batches", "0"],
        ["--max-batches", "101"],
        ["--max-batches", "-1"],
        ["--exec"],
        ["--batch-size"],
        ["--max-batches"],
    ],
)
def test_invalid_limits_and_abbreviations_fail_closed(
    args: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    monkeypatch.setattr(cli, "_make_engine", lambda _url: pytest.fail("Unexpected database access"))
    assert cli.main(["--execute", *args], environ=environment) == 1
    _assert_output(capsys, "invalid_configuration", 0, 0)


@pytest.mark.parametrize("argument", ["--batch-size", "--max-batches", "--password", "--dsn"])
def test_arbitrary_arguments_are_not_echoed(
    argument: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    marker = json.dumps({"nested": {"password": uuid.uuid4().hex}})
    monkeypatch.setattr(cli, "_make_engine", lambda _url: pytest.fail("Unexpected database access"))
    assert cli.main(["--execute", argument, marker], environ=environment) == 1
    _assert_output(capsys, "invalid_configuration", 0, 0)


@pytest.mark.parametrize(
    "kind",
    ["scheme", "driver", "password", "host", "username", "database", "query", "port", "malformed"],
)
def test_connection_contract_rejects_implicit_or_arbitrary_options(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    url = cli.make_url(environment["SECURITY_MAINTENANCE_DATABASE_URL"])
    fields: dict[str, Any] = {
        "drivername": url.drivername,
        "username": url.username,
        "password": url.password,
        "host": url.host,
        "port": url.port,
        "database": url.database,
    }
    if kind in {"password", "host", "username", "database"}:
        fields[kind] = None
    if kind in {"scheme", "driver"}:
        fields["drivername"] = "sqlite" if kind == "scheme" else "postgresql+asyncpg"
    if kind == "query":
        fields["query"] = {"options": "-c statement_timeout=0"}
    value = URL.create(**fields).render_as_string(hide_password=False)
    if kind == "port":
        value = value.replace(":5434/", f":{uuid.uuid4().hex}/")
    if kind == "malformed":
        value = json.dumps({"password": uuid.uuid4().hex})
    monkeypatch.setattr(cli, "_make_engine", lambda _url: pytest.fail("Unexpected database access"))
    assert cli.main(["--execute"], environ={"SECURITY_MAINTENANCE_DATABASE_URL": value}) == 1
    _assert_output(capsys, "invalid_configuration", 0, 0)


def test_engine_has_fixed_timeouts_and_no_pool_or_echo(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
) -> None:
    captured: dict[str, Any] = {}
    sentinel = object()

    def construct(url: URL, **kwargs: Any) -> object:
        captured.update(kwargs)
        assert url.drivername == "postgresql+psycopg"
        return sentinel

    monkeypatch.setattr(cli, "create_engine", construct)
    assert (
        cli._make_engine(cli.make_url(environment["SECURITY_MAINTENANCE_DATABASE_URL"])) is sentinel
    )
    assert captured == {
        "poolclass": NullPool,
        "echo": False,
        "hide_parameters": True,
        "connect_args": {
            "connect_timeout": 5,
            "options": "-c statement_timeout=30000 -c lock_timeout=3000",
        },
    }


def test_each_batch_commits_before_next_with_no_retries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    engine = _Engine([_row(2, True), _row(1, False)])
    _install(monkeypatch, engine)
    previous_logging = logging.root.manager.disable
    assert cli.main(["--execute", "--batch-size", "2"], environ=environment) == 0
    assert logging.root.manager.disable == previous_logging
    assert engine.trace == ["begin", "execute", "commit", "begin", "execute", "commit", "dispose"]
    assert engine.parameters == [{"batch_size": 2}, {"batch_size": 2}]
    _assert_output(capsys, "drained", 3, 2)


def test_default_batch_limit_is_bounded_and_reports_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    engine = _Engine([_row(1000, True)] * 11)
    _install(monkeypatch, engine)
    assert cli.main(["--execute"], environ=environment) == 2
    assert len(engine.parameters) == 10
    assert engine.parameters == [{"batch_size": 1000}] * 10
    _assert_output(capsys, "incomplete", 10000, 10)


@pytest.mark.parametrize("count", [0, 1])
def test_remaining_expired_is_not_false_success_at_limit(
    count: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    engine = _Engine([_row(count, True)])
    _install(monkeypatch, engine)
    assert cli.main(["--execute", "--max-batches", "1"], environ=environment) == 2
    _assert_output(capsys, "incomplete", count, 1)


def test_locked_backlog_stops_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    engine = _Engine([_row(0, True), _row(1, False)])
    _install(monkeypatch, engine)
    assert cli.main(["--execute"], environ=environment) == 2
    assert len(engine.parameters) == 1
    _assert_output(capsys, "incomplete", 0, 1)


def test_empty_database_is_drained(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    engine = _Engine([_row()])
    _install(monkeypatch, engine)
    assert cli.main(["--execute"], environ=environment) == 0
    _assert_output(capsys, "drained", 0, 1)


@pytest.mark.parametrize(
    "response",
    [
        [],
        _row() * 2,
        [{"deleted_count": 1}],
        [{"deleted_count": 1, "remaining_expired": False, "extra": 1}],
        _row(True),
        _row(-1),
        _row(1001),
        _row("1"),
        _row(1.0),
        _row(1, "false"),
        _row(1, 0),
        _row(1, None),
    ],
)
def test_invalid_response_rolls_back_and_never_advances_counts(
    response: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    engine = _Engine([_row(1, True), response, _row()])
    _install(monkeypatch, engine)
    assert cli.main(["--execute"], environ=environment) == 1
    assert engine.trace == ["begin", "execute", "commit", "begin", "execute", "rollback", "dispose"]
    _assert_output(capsys, "database_failure", 1, 1)


@pytest.mark.parametrize("failure", ["factory", "execute", "commit", "dispose"])
def test_database_failures_are_sanitized_and_count_only_acknowledged_commits(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: dict[str, str],
) -> None:
    marker = uuid.uuid4().hex
    engine = _Engine([_row(1, True), _row(2, False)])
    if failure == "factory":

        def fail(_url: URL) -> None:
            logging.getLogger("sqlalchemy.engine").critical("%s", {"password": marker})
            raise RuntimeError(marker)

        monkeypatch.setattr(cli, "_make_engine", fail)
    else:
        _install(monkeypatch, engine)
    if failure == "execute":
        engine.responses[1] = RuntimeError(marker)
    elif failure == "commit":
        engine.commit_failure = 1
    elif failure == "dispose":
        engine.disposal_failure = True
    assert cli.main(["--execute"], environ=environment) == 1
    expected = {"factory": (0, 0), "execute": (1, 1), "commit": (1, 1), "dispose": (3, 2)}
    _assert_output(capsys, "database_failure", *expected[failure])


@pytest.mark.parametrize("mode", ["help", "invalid", "missing_execute"])
def test_standalone_process_outputs_no_environment_or_argument_secrets(
    mode: str,
    environment: dict[str, str],
) -> None:
    marker = uuid.uuid4().hex
    args = {
        "help": ["--help"],
        "invalid": ["--execute", "--batch-size", json.dumps({"secret": marker})],
        "missing_execute": [],
    }[mode]
    process = subprocess.run(
        [sys.executable, "-m", "app.maintenance.security_audit_retention", *args],
        env={**os.environ, **environment, "DATABASE_URL": marker, "MIGRATION_DATABASE_URL": marker},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert process.returncode == (0 if mode == "help" else 1)
    assert process.stderr == ""
    assert marker not in process.stdout
    assert environment["SECURITY_MAINTENANCE_DATABASE_URL"] not in process.stdout
    assert "Traceback" not in process.stdout
    if mode != "help":
        assert json.loads(process.stdout) == {
            "status": "invalid_configuration",
            "deleted_count": 0,
            "batches": 0,
        }
