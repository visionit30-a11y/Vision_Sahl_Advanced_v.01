"""Interactive identity administration keeps secrets in memory and uses one DB boundary."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import InterfaceError

from app.db.identity_bootstrap import (
    BootstrapResult,
    BootstrapTenant,
    PasswordResetSnapshot,
)
from app.maintenance import identity_bootstrap


class FakeDatabase:
    last: FakeDatabase | None = None

    def __init__(self, database_url: str) -> None:
        assert database_url == "postgresql+psycopg://bootstrap:secret@localhost/sahl_dev"
        self.tenants = AsyncMock(return_value=[BootstrapTenant(uuid.uuid7(), "Tenant A")])
        self.bootstrap_admin = AsyncMock(
            return_value=BootstrapResult(uuid.uuid7(), uuid.uuid7(), uuid.uuid7())
        )
        self.password_snapshot = AsyncMock(return_value=PasswordResetSnapshot(uuid.uuid7(), 1, 1))
        self.reset_password = AsyncMock(return_value=2)
        self.close = AsyncMock()
        FakeDatabase.last = self


class FakePasswordService:
    def __init__(self, *, max_concurrency: int) -> None:
        assert max_concurrency == 2

    hash_password = AsyncMock(return_value="$argon2id$redacted")


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        app_env="development",
        password_hash_concurrency=2,
        required_identity_bootstrap_database_url=(
            "postgresql+psycopg://bootstrap:secret@localhost/sahl_dev"
        ),
    )


@pytest.mark.parametrize("action", ["bootstrap-admin", "reset-password"])
async def test_command_uses_interactive_secret_and_never_prints_it(
    action: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "A private password value"
    answers = iter(["member@example.test", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(identity_bootstrap.getpass, "getpass", lambda _prompt: secret)
    monkeypatch.setattr(identity_bootstrap, "get_settings", _settings)
    monkeypatch.setattr(identity_bootstrap, "IdentityBootstrapDatabase", FakeDatabase)
    monkeypatch.setattr(identity_bootstrap, "PasswordService", FakePasswordService)

    result = await identity_bootstrap._run(
        identity_bootstrap.Options(action, force_password_change=True)
    )

    assert result == 0
    assert FakeDatabase.last is not None
    if action == "bootstrap-admin":
        FakeDatabase.last.bootstrap_admin.assert_awaited_once()
    else:
        FakeDatabase.last.reset_password.assert_awaited_once()
    FakeDatabase.last.close.assert_awaited_once()
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err


def test_command_refuses_nondevelopment_before_database_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        identity_bootstrap,
        "get_settings",
        lambda: SimpleNamespace(app_env="production"),
    )
    assert identity_bootstrap.main(["reset-password"]) == 1


def test_command_reports_password_policy_without_echoing_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "short-secret"
    monkeypatch.setattr("builtins.input", lambda _prompt: "member@example.test")
    monkeypatch.setattr(identity_bootstrap.getpass, "getpass", lambda _prompt: secret)
    monkeypatch.setattr(identity_bootstrap, "get_settings", _settings)

    assert identity_bootstrap.main(["reset-password"]) == 1
    captured = capsys.readouterr()
    assert "15 to 128 Unicode code points" in captured.err
    assert secret not in captured.out + captured.err


def test_command_reports_password_confirmation_without_echoing_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secrets = iter(["A valid private password", "A different private password"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "member@example.test")
    monkeypatch.setattr(identity_bootstrap.getpass, "getpass", lambda _prompt: next(secrets))
    monkeypatch.setattr(identity_bootstrap, "get_settings", _settings)

    assert identity_bootstrap.main(["reset-password"]) == 1
    captured = capsys.readouterr()
    assert "Password confirmation does not match" in captured.err
    assert "A valid private password" not in captured.out + captured.err
    assert "A different private password" not in captured.out + captured.err


def test_command_redacts_database_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = "database-password-marker"

    async def fail(_options: identity_bootstrap.Options) -> int:
        raise InterfaceError("connection", {"password": marker}, RuntimeError(marker))

    monkeypatch.setattr(identity_bootstrap, "_run", fail)

    assert identity_bootstrap.main(["reset-password"]) == 1
    captured = capsys.readouterr()
    assert "database operation failed" in captured.err
    assert marker not in captured.out + captured.err


def test_command_reports_only_safe_database_sqlstate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = "database-secret-marker"
    original = RuntimeError(marker)
    original.sqlstate = "42501"  # type: ignore[attr-defined]

    async def fail(_options: identity_bootstrap.Options) -> int:
        raise InterfaceError("connection", {"password": marker}, original)

    monkeypatch.setattr(identity_bootstrap, "_run", fail)

    assert identity_bootstrap.main(["reset-password"]) == 1
    captured = capsys.readouterr()
    assert "SQLSTATE 42501" in captured.err
    assert marker not in captured.out + captured.err
