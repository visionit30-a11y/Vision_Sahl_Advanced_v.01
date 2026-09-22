"""Interactive development identity bootstrap and administrative password reset."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import uuid
from dataclasses import dataclass

from app.core.config import get_settings
from app.db.identity_bootstrap import BootstrapTenant, IdentityBootstrapDatabase
from app.models.authorization import new_role_id
from app.models.identity import new_membership_id, new_user_id, normalize_email
from app.security.passwords import PasswordPolicyError, PasswordService


@dataclass(frozen=True, slots=True)
class Options:
    action: str
    force_password_change: bool


class PasswordConfirmationError(ValueError):
    """A safe input error that never carries either password value."""


def _options(argv: list[str]) -> Options:
    parser = argparse.ArgumentParser(description="Trusted local identity administration.")
    parser.add_argument("action", choices=("bootstrap-admin", "reset-password"))
    parser.add_argument("--force-password-change", action="store_true")
    values = parser.parse_args(argv)
    return Options(values.action, values.force_password_change)


def _secret() -> str:
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise PasswordConfirmationError("Password confirmation does not match.")
    return first


def _select_tenant(tenants: list[BootstrapTenant]) -> uuid.UUID:
    if not tenants:
        raise RuntimeError("No active tenant is available.")
    for index, tenant in enumerate(tenants, 1):
        print(f"{index}. {tenant.name}")
    selected = int(input("Tenant number: "))
    if selected < 1 or selected > len(tenants):
        raise ValueError("Tenant selection is invalid.")
    return tenants[selected - 1].id


async def _run(options: Options) -> int:
    settings = get_settings()
    if settings.app_env != "development":
        raise RuntimeError("Identity bootstrap commands run only in development.")
    email = input("Email: ").strip()
    normalized = normalize_email(email)
    password = _secret()
    password_hash = await PasswordService(
        max_concurrency=settings.password_hash_concurrency
    ).hash_password(password)
    del password

    database = IdentityBootstrapDatabase(settings.required_identity_bootstrap_database_url)
    try:
        if options.action == "bootstrap-admin":
            tenant_id = _select_tenant(list(await database.tenants()))
            row = await database.bootstrap_admin(
                tenant_id=tenant_id,
                email=email,
                normalized_email=normalized,
                password_hash=password_hash,
                user_id=uuid.UUID(str(new_user_id())),
                membership_id=uuid.UUID(str(new_membership_id())),
                role_id=uuid.UUID(str(new_role_id())),
            )
            print("Tenant Admin bootstrap completed.")
            print(f"User: {row.user_id}")
            print(f"Membership: {row.membership_id}")
            print(f"Role: {row.role_id}")
            return 0

        snapshot = await database.password_snapshot(normalized)
        if snapshot is None:
            raise RuntimeError("The requested active credential was not found.")
        revoked = await database.reset_password(
            snapshot,
            password_hash,
            force_password_change=options.force_password_change,
        )
        print("Password reset completed; prior sessions were revoked.")
        print(f"Revoked sessions: {revoked}")
        return 0
    finally:
        await database.close()


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(_run(_options(sys.argv[1:] if argv is None else argv)))
    except PasswordPolicyError as error:
        print(str(error), file=sys.stderr)
        return 1
    except PasswordConfirmationError:
        print("Password confirmation does not match.", file=sys.stderr)
        return 1
    except ValueError, RuntimeError:
        print("Identity administration could not be completed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
