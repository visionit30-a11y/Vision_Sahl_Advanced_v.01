"""Configuration behaviour."""

from __future__ import annotations

from app.core.config import Settings


def test_cors_origins_are_parsed_into_a_list() -> None:
    settings = Settings(_env_file=None, cors_origins="http://a.test, http://b.test ,")

    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_log_level_is_normalised() -> None:
    settings = Settings(_env_file=None, log_level="debug")

    assert settings.log_level == "DEBUG"


def test_redis_is_disabled_by_default_in_phase_0() -> None:
    settings = Settings(_env_file=None)

    assert settings.redis_enabled is False


def test_production_flag() -> None:
    assert Settings(_env_file=None, app_env="production").is_production is True
    assert Settings(_env_file=None, app_env="development").is_production is False
