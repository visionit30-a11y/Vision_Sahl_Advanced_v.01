"""Alembic environment.

Two things are settled here and nowhere else.

The engine is synchronous while the application engine is asynchronous, over
the same psycopg3 URL (ADR-0005): a tool that runs outside the request cycle
has nothing to gain from async and something to lose in complexity.

The connection is the *migration* role's, never the runtime role's. A table's
owner bypasses row level security unless the table forces it, so if migrations
and the application shared one role every isolation policy would be one missing
FORCE away from being inert - and its tests would pass for the wrong reason.
The runtime URL is therefore never used as the migration URL, there is no
fallback between them, and the role actually connected is verified before a
single statement runs (ADR-0017).
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool, text
from sqlalchemy.engine import Connection, make_url

API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()

# "%" must be escaped: ConfigParser interpolates the value.
config.set_main_option(
    "sqlalchemy.url", settings.required_migration_database_url.replace("%", "%%")
)

target_metadata = Base.metadata


class MigrationRoleError(RuntimeError):
    """Raised when migrations are about to run as the wrong database role."""


def runtime_role_name() -> str | None:
    """The role the application connects with, taken from the runtime URL."""
    return make_url(settings.database_url).username


def assert_not_running_as_the_application_role(connection: Connection) -> None:
    """Stop before any DDL if this connection is the application's own role.

    This is a gate, not a warning, and it holds in every environment: there is
    none in which the runtime role should be creating schema objects. It reads
    the role from the live connection rather than trusting the URL, so it also
    catches a URL that names one role while the server authenticates another.
    """
    current_user = connection.execute(text("SELECT current_user")).scalar_one()
    application_role = runtime_role_name()

    if application_role is not None and current_user == application_role:
        raise MigrationRoleError(
            f"Migrations are connected as {current_user!r}, which is the role the application "
            "runs with. Objects created here would be owned by the application role, and a "
            "table's owner bypasses row level security. Point MIGRATION_DATABASE_URL at the "
            "migration role and run this again."
        )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database, as the migration role."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        assert_not_running_as_the_application_role(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
