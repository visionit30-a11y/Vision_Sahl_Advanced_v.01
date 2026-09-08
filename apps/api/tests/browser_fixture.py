"""Isolated real-PostgreSQL browser fixtures; JSON pipes are consumed only in memory.

Not imported by the application. No test HTTP endpoints, stored credentials,
or Playwright storageState files. Failures never echo database URLs or secrets.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
import uuid
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.postgres import PostgresSessionStore
from app.auth.sessions import SessionService
from app.auth.tenants import PostgresMembershipAuthority, TrustedTenantService
from app.authorization.permissions import Permission
from app.core.config import get_settings
from app.security.passwords import PasswordService


def _owned_tenants(state: dict[str, str], migration: Engine) -> list[str]:
    """Validate every deletion target, including users; absent fixtures are harmless."""
    tenants: list[str] = []
    with migration.connect() as conn:
        for suffix in ("a", "b", "c"):
            tenant = str(uuid.UUID(state[f"tenant_{suffix}"]))
            slug = conn.scalar(text("SELECT slug FROM public.tenants WHERE id=:id"), {"id": tenant})
            if slug is not None:
                if slug != f"browser-g5-{tenant}":
                    raise RuntimeError("Fixture tenant ownership could not be proved.")
                tenants.append(tenant)
        for key in ("user", "foreign_user"):
            user = str(uuid.UUID(state[key]))
            email = conn.scalar(
                text("SELECT normalized_email FROM auth.users WHERE id=:id"), {"id": user}
            )
            if email is not None and email != f"browser-g5-{user}@example.test":
                raise RuntimeError("Fixture user ownership could not be proved.")
    return tenants


async def _cleanup(state: dict[str, str], migration: Engine, runtime: AsyncEngine) -> None:
    tenants = _owned_tenants(state, migration)
    for tenant in tenants:
        async with runtime.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id',:tenant,true)"), {"tenant": tenant}
            )
            for statement in (
                "DELETE FROM app.user_ui_settings WHERE tenant_id=:tenant",
                "DELETE FROM app.tenant_ui_settings WHERE tenant_id=:tenant",
                "DELETE FROM auth.membership_roles WHERE tenant_id=:tenant",
                "DELETE FROM auth.role_permissions WHERE tenant_id=:tenant",
                "DELETE FROM auth.roles WHERE tenant_id=:tenant",
            ):
                await conn.execute(text(statement), {"tenant": tenant})
    with migration.begin() as conn:
        params = {"u": str(uuid.UUID(state["user"])), "v": str(uuid.UUID(state["foreign_user"]))}
        conn.execute(text("DELETE FROM auth.security_events WHERE user_id IN (:u,:v)"), params)
        conn.execute(text("DELETE FROM auth.sessions WHERE user_id IN (:u,:v)"), params)
        conn.execute(text("DELETE FROM auth.tenant_memberships WHERE user_id IN (:u,:v)"), params)
        conn.execute(text("DELETE FROM auth.password_credentials WHERE user_id IN (:u,:v)"), params)
        conn.execute(text("DELETE FROM auth.users WHERE id IN (:u,:v)"), params)
        for tenant in tenants:
            conn.execute(text("DELETE FROM public.tenants WHERE id=:tenant"), {"tenant": tenant})
    # Verify the committed result using exact fixture IDs. The tenant foreign
    # keys also prevent any settings/role rows surviving deletion of their tenant.
    with migration.connect() as conn:
        user_count = conn.scalar(
            text("SELECT count(*) FROM auth.users WHERE id IN (:u,:v)"), params
        )
        tenant_count = conn.scalar(
            text("SELECT count(*) FROM public.tenants WHERE id IN (:a,:b,:c)"),
            {suffix: str(uuid.UUID(state[f"tenant_{suffix}"])) for suffix in ("a", "b", "c")},
        )
        if user_count != 0 or tenant_count != 0:
            raise RuntimeError("Browser fixture cleanup did not remove its exact owned rows.")


async def main(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if settings.app_env not in {"development", "test"}:
        raise RuntimeError("Browser fixtures require a local test environment.")
    migration = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    runtime = create_async_engine(settings.database_url, poolclass=NullPool)
    seeded_state: dict[str, str] | None = None
    try:
        if payload["action"] in {"seed", "seed_login"}:
            state = {
                key: str(uuid.uuid7())
                for key in (
                    "user",
                    "foreign_user",
                    "tenant_a",
                    "tenant_b",
                    "tenant_c",
                    "membership_a",
                    "membership_b",
                    "membership_c",
                    "role_a",
                    "role_b",
                )
            }
            seeded_state = state
            with migration.begin() as conn:
                for key in ("user", "foreign_user"):
                    conn.execute(
                        text(
                            "INSERT INTO auth.users(id,email,normalized_email,status) "
                            "VALUES (:id,:email,:email,'active')"
                        ),
                        {"id": state[key], "email": f"browser-g5-{state[key]}@example.test"},
                    )
                for suffix in ("a", "b", "c"):
                    tenant = state[f"tenant_{suffix}"]
                    conn.execute(
                        text(
                            "INSERT INTO public.tenants(id,slug,name_ar,name_en,status) "
                            "VALUES (:id,:slug,:name,:name,'active')"
                        ),
                        {"id": tenant, "slug": f"browser-g5-{tenant}", "name": suffix.upper()},
                    )
                    conn.execute(
                        text(
                            "INSERT INTO auth.tenant_memberships "
                            "(id,user_id,tenant_id,status,joined_at) VALUES "
                            "(:id,:user,:tenant,'active',clock_timestamp())"
                        ),
                        {
                            "id": state[f"membership_{suffix}"],
                            "user": state["foreign_user" if suffix == "c" else "user"],
                            "tenant": tenant,
                        },
                    )
            for suffix, theme in (("a", "navy-institutional"), ("b", "green-institutional")):
                async with runtime.begin() as conn:
                    await conn.execute(
                        text("SELECT set_config('app.tenant_id',:tenant,true)"),
                        {"tenant": state[f"tenant_{suffix}"]},
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO auth.roles(id,tenant_id,key,display_name) "
                            "VALUES (:id,:tenant,'browser_settings','Browser settings')"
                        ),
                        {"id": state[f"role_{suffix}"], "tenant": state[f"tenant_{suffix}"]},
                    )
                    for permission in (
                        Permission.TENANT_UI_SETTINGS_MANAGE,
                        Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF,
                    ):
                        await conn.execute(
                            text(
                                "INSERT INTO auth.role_permissions"
                                "(tenant_id,role_id,permission_id) "
                                "VALUES (:tenant,:role,:permission)"
                            ),
                            {
                                "tenant": state[f"tenant_{suffix}"],
                                "role": state[f"role_{suffix}"],
                                "permission": permission.value,
                            },
                        )
                    await conn.execute(
                        text(
                            "INSERT INTO auth.membership_roles(tenant_id,membership_id,role_id) "
                            "VALUES (:tenant,:membership,:role)"
                        ),
                        {
                            "tenant": state[f"tenant_{suffix}"],
                            "membership": state[f"membership_{suffix}"],
                            "role": state[f"role_{suffix}"],
                        },
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO app.tenant_ui_settings(tenant_id,settings) "
                            "VALUES (:tenant,CAST(:settings AS jsonb))"
                        ),
                        {
                            "tenant": state[f"tenant_{suffix}"],
                            "settings": json.dumps({"theme": theme}),
                        },
                    )
            if payload["action"] == "seed_login":
                state["password"] = secrets.token_urlsafe(32)
                state["email"] = f"browser-g5-{state['user']}@example.test"
                password_hash = await PasswordService().hash_password(state["password"])
                with migration.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO auth.password_credentials(user_id,password_hash) "
                            "VALUES (:id,:hash)"
                        ),
                        {"id": state["user"], "hash": password_hash},
                    )
                return state
            async with runtime.begin() as conn:
                sessions = SessionService(PostgresSessionStore(conn))
                issued = await sessions.issue(uuid.UUID(state["user"]), 1)
                switched = await TrustedTenantService(
                    sessions, PostgresMembershipAuthority(conn)
                ).switch(issued.secrets.bearer, uuid.UUID(state["membership_a"]))
                state["bearer"] = switched.issued_session.secrets.bearer
            return state

        state = payload["state"]
        # Validate fixture ownership before any targeted cleanup or fixture mutation.
        tenants = _owned_tenants(state, migration)
        if payload["action"] == "deny_tenant":
            if state["tenant_a"] not in tenants:
                raise RuntimeError("Fixture tenant is unavailable.")
            async with runtime.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id',:tenant,true)"),
                    {"tenant": state["tenant_a"]},
                )
                await conn.execute(
                    text(
                        "DELETE FROM auth.role_permissions WHERE role_id=:role "
                        "AND permission_id=:permission"
                    ),
                    {
                        "role": state["role_a"],
                        "permission": Permission.TENANT_UI_SETTINGS_MANAGE.value,
                    },
                )
            return {}
        if payload["action"] == "cleanup":
            await _cleanup(state, migration, runtime)
            return {}
        raise RuntimeError("Unknown fixture operation.")
    except BaseException:
        if seeded_state is not None:
            await _cleanup(seeded_state, migration, runtime)
        raise
    finally:
        await runtime.dispose()
        migration.dispose()


if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                result = runner.run(main(json.load(sys.stdin)))
        else:
            result = asyncio.run(main(json.load(sys.stdin)))
        # Read by Playwright's pipe, never forwarded to console/artifacts.
        sys.stdout.write(json.dumps(result))
    except Exception:  # noqa: BLE001 - suppress fixture secrets in error paths
        sys.stderr.write("Real PostgreSQL browser fixture failed.\n")
        raise SystemExit(1) from None
