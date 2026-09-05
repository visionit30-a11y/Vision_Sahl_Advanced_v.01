"""Configuration behaviour."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from app.core.config import Settings


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
