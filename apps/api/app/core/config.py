"""Application configuration.

All configuration is read from environment variables (or a local .env file).
No secret is ever hard-coded here - see SRS TS-10.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = API_DIR.parents[1]

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    """Runtime settings for the API."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", API_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Sahl Developer Platform"
    app_env: Environment = "development"
    app_version: str = "0.1.0"

    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    database_url: str = "postgresql+psycopg://sahl_app:sahl_app@127.0.0.1:5432/sahl_dev"

    redis_enabled: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        return value.strip().upper()

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list (configured as a comma separated string)."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
