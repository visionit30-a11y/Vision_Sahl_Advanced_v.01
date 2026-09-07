"""Configuration behaviour."""

from __future__ import annotations

import pytest
from pydantic_settings import SettingsConfigDict

from app.core.config import MigrationDatabaseUrlMissingError, Settings


class IsolatedSettings(Settings):
    """Settings that ignore the developer's local .env file.

    Tests must assert the declared defaults, not whatever happens to sit in the
    machine's .env at the time.
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)


def test_cors_origins_are_parsed_into_a_list() -> None:
    settings = IsolatedSettings(cors_origins="http://a.test, http://b.test ,")

    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_log_level_is_normalised() -> None:
    settings = IsolatedSettings(log_level="debug")

    assert settings.log_level == "DEBUG"


def test_redis_is_disabled_by_default_in_phase_0() -> None:
    settings = IsolatedSettings()

    assert settings.redis_enabled is False


def test_production_flag() -> None:
    assert IsolatedSettings(app_env="production").is_production is True
    assert IsolatedSettings(app_env="development").is_production is False


def test_the_migration_url_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A default would silently reunite the two database roles."""
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    assert IsolatedSettings().migration_database_url is None


def test_asking_for_a_missing_migration_url_fails_rather_than_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    settings = IsolatedSettings(
        database_url="postgresql+psycopg://sahl_app:x@127.0.0.1:5433/sahl_dev"
    )

    with pytest.raises(MigrationDatabaseUrlMissingError) as failure:
        _ = settings.required_migration_database_url

    # The runtime URL must not appear as a suggestion, in the message or anywhere else.
    assert "sahl_app" not in str(failure.value)


def test_the_migration_url_is_returned_when_it_is_set() -> None:
    settings = IsolatedSettings(
        migration_database_url="postgresql+psycopg://sahl_migrator:x@127.0.0.1:5433/sahl_dev"
    )

    assert settings.required_migration_database_url.startswith(
        "postgresql+psycopg://sahl_migrator:"
    )


def test_the_two_urls_are_separate_settings() -> None:
    """One value must never be able to answer for the other."""
    settings = IsolatedSettings(
        database_url="postgresql+psycopg://sahl_app:x@127.0.0.1:5433/sahl_dev",
        migration_database_url="postgresql+psycopg://sahl_migrator:y@127.0.0.1:5433/sahl_dev",
    )

    assert settings.database_url != settings.required_migration_database_url
