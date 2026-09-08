"""Provision one disposable CI principal; never use against development or production."""

from __future__ import annotations

import logging
import os
import secrets
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def main() -> int:
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        if os.environ.get("CI") != "true" or os.environ.get("APP_ENV") != "test":
            raise ValueError
        target = make_url(os.environ["DATABASE_URL"])
        if (
            target.database != "sahl_ci"
            or target.host != "127.0.0.1"
            or target.username != "sahl_app"
            or target.drivername != "postgresql+psycopg"
            or target.query
        ):
            raise ValueError
        destination = Path(os.environ["GITHUB_ENV"])
        if not destination.is_file():
            raise ValueError
        password = secrets.token_urlsafe(32)
        with psycopg.connect(
            host=target.host,
            port=target.port or 5432,
            dbname=target.database,
            user="postgres",
            password=os.environ["PGPASSWORD"],
            connect_timeout=5,
            options=(
                "-c log_statement=none -c log_min_error_statement=panic "
                "-c log_parameter_max_length_on_error=0 -c log_error_verbosity=terse "
                "-c log_min_duration_statement=-1 -c log_min_duration_sample=-1 "
                "-c log_transaction_sample_rate=0 -c log_duration=off"
            ),
        ) as connection:
            if connection.execute("SELECT current_database()").fetchone() != ("sahl_ci",):
                raise ValueError
            connection.execute(
                sql.SQL("ALTER ROLE sahl_maintenance_test PASSWORD {}").format(
                    sql.Literal(password)
                )
            )
        maintenance = target.set(username="sahl_maintenance_test", password=password)
        # GITHUB_ENV is an ephemeral runner file, not a source file or artifact.
        # Do not echo this assignment or send its value through an output/masking command.
        with destination.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                "SECURITY_MAINTENANCE_DATABASE_URL="
                + maintenance.render_as_string(hide_password=False)
                + "\n"
            )
        print("Isolated audit retention identity prepared.")
        return 0
    except Exception:  # noqa: BLE001 - fixed diagnostic, no DSN/driver/SQL/parameters
        print("Isolated audit retention identity setup failed.", file=sys.stderr)
        return 1
    finally:
        logging.disable(previous)


if __name__ == "__main__":
    raise SystemExit(main())
