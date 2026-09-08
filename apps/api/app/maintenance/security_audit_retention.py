"""Bounded audit retention runner with a dedicated, environment-only capability.

Each batch commits independently through auth.prune_security_events(integer).
The database owns the retention cutoff, atomic audit event, and privilege boundary.
No application settings, dotenv file, scheduler, or HTTP route is involved.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, Never

from sqlalchemy import URL, Engine, create_engine, make_url, text
from sqlalchemy.pool import NullPool

_DATABASE_ENV = "SECURITY_MAINTENANCE_DATABASE_URL"
_PRUNE = text(
    "SELECT deleted_count, remaining_expired FROM auth.prune_security_events(:batch_size)"
)
Status = Literal["drained", "incomplete", "invalid_configuration", "database_failure"]


class _InvalidConfiguration(Exception):
    """Contains no supplied arguments, connection data, or cause text."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # argparse's normal error echoes unknown arguments and conversion inputs.
        raise _InvalidConfiguration from None


@dataclass(frozen=True, slots=True)
class _Result:
    status: Status
    deleted_count: int = 0
    batches: int = 0

    @property
    def exit_code(self) -> int:
        if self.status == "drained":
            return 0
        if self.status == "incomplete":
            return 2
        return 1


def _parser() -> _Parser:
    parser = _Parser(
        prog="python -m app.maintenance.security_audit_retention",
        description="Bounded security audit retention. The database retention policy is fixed.",
        allow_abbrev=False,
        add_help=False,
    )
    parser.add_argument("--help", action="store_true", help="show this static usage and exit")
    parser.add_argument("--execute", action="store_true", help="explicitly authorize deletion")
    parser.add_argument(
        "--batch-size", type=int, default=1000, help="rows per batch, 1 through 1000"
    )
    parser.add_argument("--max-batches", type=int, default=10, help="batch limit, 1 through 100")
    return parser


def _validated_url(value: str | None) -> URL:
    if not value:
        raise _InvalidConfiguration
    try:
        url = make_url(value)
        if (
            url.drivername != "postgresql+psycopg"
            or not url.username
            or not url.password
            or not url.host
            or not url.database
            or url.query
        ):
            raise _InvalidConfiguration
        return url
    except Exception:  # noqa: BLE001 - never expose URL parser inputs or credentials
        raise _InvalidConfiguration from None


def _make_engine(url: URL) -> Engine:
    return create_engine(
        url,
        poolclass=NullPool,
        echo=False,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=30000 -c lock_timeout=3000",
        },
    )


@contextmanager
def _closed_diagnostics() -> Iterator[None]:
    # Standalone execution needs no server logger setup or application imports.
    # Driver/SQLAlchemy loggers must not emit raw connection diagnostics either.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def _run_batches(engine: Engine, *, batch_size: int, max_batches: int) -> _Result:
    deleted_count = 0
    batches = 0
    try:
        for _ in range(max_batches):
            with engine.begin() as connection:
                rows = connection.execute(_PRUNE, {"batch_size": batch_size}).mappings().all()
                if len(rows) != 1 or set(rows[0]) != {"deleted_count", "remaining_expired"}:
                    raise ValueError("Invalid retention response")
                deleted = rows[0]["deleted_count"]
                remaining = rows[0]["remaining_expired"]
                if (
                    type(deleted) is not int
                    or not 0 <= deleted <= batch_size
                    or type(remaining) is not bool
                ):
                    raise ValueError("Invalid retention response")
            # Count only acknowledged commits; failed batches never advance totals.
            deleted_count += deleted
            batches += 1
            if not remaining:
                return _Result("drained", deleted_count, batches)
            if deleted == 0:
                # Locked expired rows are backlog, never a false drained result.
                return _Result("incomplete", deleted_count, batches)
        return _Result("incomplete", deleted_count, batches)
    except Exception, KeyboardInterrupt:  # noqa: BLE001 - closed CLI failure boundary
        return _Result("database_failure", deleted_count, batches)


def _execute(url: URL, *, batch_size: int, max_batches: int) -> _Result:
    engine: Engine | None = None
    result = _Result("database_failure")
    try:
        engine = _make_engine(url)
        result = _run_batches(engine, batch_size=batch_size, max_batches=max_batches)
    except Exception, KeyboardInterrupt:  # noqa: BLE001 - includes engine creation failures
        result = _Result("database_failure")
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception, KeyboardInterrupt:  # noqa: BLE001 - no driver diagnostics
                result = _Result("database_failure", result.deleted_count, result.batches)
    return result


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    """Emit closed status/count fields only; never input, exceptions or a DSN."""
    with _closed_diagnostics():
        try:
            parser = _parser()
            args = parser.parse_args(argv)
            if args.help:
                parser.print_help()
                return 0
            if (
                not args.execute
                or not 1 <= args.batch_size <= 1000
                or not 1 <= args.max_batches <= 100
            ):
                raise _InvalidConfiguration
            environment = os.environ if environ is None else environ
            url = _validated_url(environment.get(_DATABASE_ENV))
            result = _execute(url, batch_size=args.batch_size, max_batches=args.max_batches)
        except Exception, KeyboardInterrupt:  # noqa: BLE001 - no argparse/config input echo
            result = _Result("invalid_configuration")
    print(
        json.dumps(
            {
                "status": result.status,
                "deleted_count": result.deleted_count,
                "batches": result.batches,
            },
            separators=(",", ":"),
        )
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
