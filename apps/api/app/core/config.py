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


class MigrationDatabaseUrlMissingError(RuntimeError):
    """Raised when migrations are attempted without a migration role URL."""


class AuthHmacKeyMissingError(RuntimeError):
    """Raised when authentication key digests cannot be generated safely."""


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
    api_port: int = 8010
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # The runtime URL. It must name the application role, which owns nothing and
    # is subject to row level security.
    database_url: str = "postgresql+psycopg://sahl_app:sahl_app@127.0.0.1:5433/sahl_dev"

    # The migration URL, deliberately without a default. Alembic runs as the
    # migration role, which owns the schema; the application role must never
    # create an object, because a table's owner bypasses row level security
    # unless the table forces it. Falling back to database_url here would put
    # the two roles back together silently, so there is no fallback: a missing
    # value is an error at the point migrations are run, not a quiet downgrade
    # to the runtime role.
    migration_database_url: str | None = None

    redis_enabled: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"

    password_hash_concurrency: int = 2
    session_idle_timeout_minutes: int = 30
    session_absolute_timeout_hours: int = 8
    max_concurrent_sessions: int = 5
    session_last_seen_interval_seconds: int = 60
    preauth_csrf_lifetime_minutes: int = 10
    auth_hmac_key: str | None = None
    auth_hmac_key_id: int = 1

    @field_validator("password_hash_concurrency")
    @classmethod
    def _validate_password_hash_concurrency(cls, value: int) -> int:
        if not 1 <= value <= 4:
            raise ValueError("Password hashing concurrency must be between 1 and 4.")
        return value

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

    @property
    def required_migration_database_url(self) -> str:
        """The migration URL, or a clear failure explaining what is missing.

        Alembic calls this rather than reading the attribute, so a missing
        setting stops the migration instead of running it as whatever role the
        runtime happens to use.
        """
        if not self.migration_database_url:
            raise MigrationDatabaseUrlMissingError(
                "MIGRATION_DATABASE_URL is not set. Migrations run as the migration role, "
                "which owns the schema; the application role must never own a table because "
                "an owner bypasses row level security. Set MIGRATION_DATABASE_URL to the "
                "migration role's connection string. There is no fallback to DATABASE_URL."
            )
        return self.migration_database_url

    @property
    def required_auth_hmac_key(self) -> bytes:
        """Return the configured HMAC key, rejecting missing or short secrets."""
        if self.auth_hmac_key is None or len(self.auth_hmac_key.encode()) < 32:
            raise AuthHmacKeyMissingError(
                "AUTH_HMAC_KEY must contain at least 32 bytes; there is no insecure fallback."
            )
        return self.auth_hmac_key.encode()


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
