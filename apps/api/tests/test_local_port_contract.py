"""Static contract for the fixed local ports and safe Windows launcher."""

from pathlib import Path

from pydantic_settings import SettingsConfigDict

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[3]


class IsolatedSettings(Settings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)


def test_local_api_port_is_8010_at_each_runtime_entry_point() -> None:
    assert IsolatedSettings().api_port == 8010
    assert "API_PORT=8010" in (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "$API_PORT = 8010" in (ROOT / "scripts/02-run.ps1").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8010" in (ROOT / "apps/web/vite.config.ts").read_text(encoding="utf-8")


def test_guarded_launcher_fails_closed_without_killing_foreign_owner() -> None:
    source = (ROOT / "scripts/06-update-and-run.ps1").read_text(encoding="utf-8")
    assert "$apiPort = 8010" in source
    assert "Test-ProcessBelongsToProject" in source
    assert "Nothing was stopped" in source
    assert "port 8000 is not a fallback" in source
    assert "random" not in source.casefold()


def test_port_cleanup_requires_checkout_ownership_proof() -> None:
    source = (ROOT / "scripts/_common.ps1").read_text(encoding="utf-8")
    assert "function Test-ProcessBelongsToProject" in source
    clear_port = source[source.index("function Clear-DevelopmentPort") :]
    assert "Test-ProcessBelongsToProject -ProcessId $owner.Id" in clear_port
