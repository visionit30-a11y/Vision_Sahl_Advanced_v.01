"""G4 disposable bootstrap refuses other environments and never emits credentials."""

from __future__ import annotations

import importlib.util
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import URL, make_url


@pytest.fixture
def bootstrap() -> Any:
    path = Path(__file__).resolve().parents[3] / ".github/ci/security-maintenance-fixture.py"
    spec = importlib.util.spec_from_file_location("maintenance_fixture", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def setup_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    destination = tmp_path / "github-env"
    destination.touch()
    url = URL.create(
        "postgresql+psycopg",
        username="sahl_app",
        password=uuid.uuid4().hex,
        host="127.0.0.1",
        port=5434,
        database="sahl_ci",
    )
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    monkeypatch.setenv("PGPASSWORD", uuid.uuid4().hex)
    monkeypatch.setenv("GITHUB_ENV", str(destination))
    return destination


@pytest.mark.parametrize(
    "variable,value",
    [
        ("CI", "false"),
        ("APP_ENV", "development"),
        ("DATABASE_URL", "postgresql+psycopg://localhost/sahl_dev"),
        ("DATABASE_URL", "not-a-database-url"),
        ("GITHUB_ENV", ""),
    ],
)
def test_bootstrap_rejects_unapproved_context_before_connect(
    bootstrap: Any,
    setup_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variable: str,
    value: str,
) -> None:
    calls: list[object] = []
    monkeypatch.setenv(variable, value)
    monkeypatch.setattr(bootstrap.psycopg, "connect", lambda **kwargs: calls.append(kwargs))
    assert bootstrap.main() == 1
    assert calls == []
    assert setup_environment.read_text() == ""
    assert capsys.readouterr().err == "Isolated audit retention identity setup failed.\n"


def test_bootstrap_driver_failure_emits_no_secret(
    bootstrap: Any,
    setup_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = uuid.uuid4().hex
    before = logging.root.manager.disable

    def fail(**kwargs: Any) -> None:
        logging.getLogger("psycopg").critical(marker)
        raise RuntimeError(marker)

    monkeypatch.setattr(bootstrap.psycopg, "connect", fail)
    assert bootstrap.main() == 1
    assert logging.root.manager.disable == before
    output = capsys.readouterr()
    assert marker not in output.out + output.err + caplog.text
    assert output.err == "Isolated audit retention identity setup failed.\n"
    assert setup_environment.read_text() == ""


def test_bootstrap_random_credential_only_in_ephemeral_environment(
    bootstrap: Any,
    setup_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = uuid.uuid4().hex
    captured: dict[str, Any] = {}
    statements: list[object] = []

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def execute(self, statement: object) -> Connection:
            statements.append(statement)
            logging.getLogger("psycopg").critical(marker)
            return self

        def fetchone(self) -> tuple[str]:
            return ("sahl_ci",)

    def connect(**kwargs: Any) -> Connection:
        captured.update(kwargs)
        return Connection()

    monkeypatch.setattr(bootstrap.psycopg, "connect", connect)
    monkeypatch.setattr(bootstrap.secrets, "token_urlsafe", lambda length: marker)
    assert bootstrap.main() == 0
    assignment = setup_environment.read_text()
    name, value = assignment.strip().split("=", 1)
    assert name == "SECURITY_MAINTENANCE_DATABASE_URL"
    parsed = make_url(value)
    assert parsed.username == "sahl_maintenance_test" and parsed.password == marker
    assert parsed.database == "sahl_ci" and parsed.port == 5434
    assert len(statements) == 2
    for setting in (
        "log_statement=none",
        "log_min_error_statement=panic",
        "log_parameter_max_length_on_error=0",
        "log_min_duration_statement=-1",
        "log_min_duration_sample=-1",
        "log_transaction_sample_rate=0",
        "log_duration=off",
    ):
        assert setting in captured["options"]
    output = capsys.readouterr()
    assert output.out == "Isolated audit retention identity prepared.\n" and not output.err
    assert marker not in output.out + output.err + caplog.text
