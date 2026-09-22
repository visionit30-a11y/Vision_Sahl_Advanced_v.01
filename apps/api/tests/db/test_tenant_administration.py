"""Live PostgreSQL contracts for tenant administration and identity bootstrap."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.authorization.permissions import Permission
from app.core.config import Settings
from app.db.identity_bootstrap import IdentityBootstrapDatabase


@pytest.fixture
async def bootstrap_state(settings: Settings) -> AsyncIterator[dict[str, uuid.UUID | str]]:
    tenant_id, user_id, membership_id, role_id = (uuid.uuid7() for _ in range(4))
    email = f"tenant-admin-{user_id}@example.test"
    owner = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with owner.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name_ar,name_en,status) "
                "VALUES (:id,:slug,'Tenant admin test','Tenant admin test','active')"
            ),
            {"id": tenant_id, "slug": f"tenant-admin-{tenant_id}"},
        )
    database = IdentityBootstrapDatabase(settings.required_identity_bootstrap_database_url)
    try:
        result = await database.bootstrap_admin(
            tenant_id=tenant_id,
            email=email,
            normalized_email=email,
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$test$test",
            user_id=user_id,
            membership_id=membership_id,
            role_id=role_id,
        )
        yield {
            "tenant": tenant_id,
            "user": result.user_id,
            "membership": result.membership_id,
            "role": result.role_id,
            "email": email,
        }
    finally:
        await database.close()
        with owner.begin() as connection:
            connection.execute(
                text("DELETE FROM auth.security_events WHERE user_id=:user"),
                {"user": user_id},
            )
            connection.execute(
                text("DELETE FROM auth.sessions WHERE user_id=:user"), {"user": user_id}
            )
            connection.execute(
                text("SELECT set_config('app.tenant_id',:tenant,true)"),
                {"tenant": tenant_id},
            )
            connection.execute(
                text("DELETE FROM auth.membership_roles WHERE tenant_id=:tenant"),
                {"tenant": tenant_id},
            )
            connection.execute(
                text("DELETE FROM auth.role_permissions WHERE tenant_id=:tenant"),
                {"tenant": tenant_id},
            )
            connection.execute(
                text("DELETE FROM auth.roles WHERE tenant_id=:tenant"),
                {"tenant": tenant_id},
            )
            connection.execute(
                text("DELETE FROM auth.tenant_memberships WHERE tenant_id=:tenant"),
                {"tenant": tenant_id},
            )
            connection.execute(
                text("DELETE FROM public.tenants WHERE id=:tenant"), {"tenant": tenant_id}
            )
            connection.execute(
                text("DELETE FROM auth.password_credentials WHERE user_id=:user"),
                {"user": user_id},
            )
            connection.execute(text("DELETE FROM auth.users WHERE id=:user"), {"user": user_id})
        owner.dispose()


async def test_bootstrap_is_idempotent_and_grants_only_tenant_permissions(
    bootstrap_state: dict[str, uuid.UUID | str], settings: Settings
) -> None:
    database = IdentityBootstrapDatabase(settings.required_identity_bootstrap_database_url)
    try:
        result = await database.bootstrap_admin(
            tenant_id=bootstrap_state["tenant"],  # type: ignore[arg-type]
            email=str(bootstrap_state["email"]),
            normalized_email=str(bootstrap_state["email"]),
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$other$other",
            user_id=uuid.uuid7(),
            membership_id=uuid.uuid7(),
            role_id=uuid.uuid7(),
        )
    finally:
        await database.close()
    assert (result.user_id, result.membership_id, result.role_id) == (
        bootstrap_state["user"],
        bootstrap_state["membership"],
        bootstrap_state["role"],
    )
    owner = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with owner.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id',:tenant,true)"),
            {"tenant": bootstrap_state["tenant"]},
        )
        role = connection.execute(
            text("SELECT key::text,display_name,kind::text,status::text FROM auth.roles")
        ).one()
        permissions = set(
            connection.execute(text("SELECT permission_id FROM auth.role_permissions")).scalars()
        )
        assert role == (
            "tenant_admin",
            "Tenant Admin / مسؤول الجمعية",
            "tenant_admin",
            "active",
        )
        assert permissions == {
            permission.value for permission in Permission if permission.value.startswith("tenant.")
        }
        assert connection.scalar(text("SELECT count(*) FROM auth.membership_roles")) == 1
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM app.tenant_access_events "
                    "WHERE event_type='tenant_admin_bootstrapped'"
                )
            )
            == 1
        )
    owner.dispose()


async def test_admin_password_reset_revokes_sessions_and_sets_force_change(
    bootstrap_state: dict[str, uuid.UUID | str], settings: Settings
) -> None:
    session_id = uuid.uuid7()
    owner = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with owner.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO auth.sessions(id,user_id,bearer_digest,csrf_digest,security_version,"
                "created_at,authenticated_at,last_seen_at,idle_expires_at,absolute_expires_at) "
                "VALUES (:id,:user,:bearer,:csrf,1,now(),now(),now(),"
                "now()+interval '30 minutes',now()+interval '8 hours')"
            ),
            {
                "id": session_id,
                "user": bootstrap_state["user"],
                "bearer": bytes(32),
                "csrf": bytes([1]) * 32,
            },
        )
    database = IdentityBootstrapDatabase(settings.required_identity_bootstrap_database_url)
    try:
        snapshot = await database.password_snapshot(str(bootstrap_state["email"]))
        assert snapshot is not None
        assert (
            await database.reset_password(
                snapshot,
                "$argon2id$v=19$m=65536,t=3,p=4$new$new",
                force_password_change=True,
            )
            == 1
        )
    finally:
        await database.close()
    with owner.connect() as connection:
        credential = connection.execute(
            text(
                "SELECT credential_version,force_password_change "
                "FROM auth.password_credentials WHERE user_id=:user"
            ),
            {"user": bootstrap_state["user"]},
        ).one()
        assert credential == (2, True)
        assert connection.scalar(
            text("SELECT revoked_at IS NOT NULL FROM auth.sessions WHERE id=:id"),
            {"id": session_id},
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM auth.security_events "
                    "WHERE user_id=:user AND event_type='password_reset_completed'"
                ),
                {"user": bootstrap_state["user"]},
            )
            == 1
        )
    owner.dispose()


def test_tenant_directory_and_append_only_history_are_rls_scoped(
    bootstrap_state: dict[str, uuid.UUID | str], app_connection: Connection
) -> None:
    app_connection.execute(
        text("SELECT set_config('app.tenant_id',:tenant,true)"),
        {"tenant": bootstrap_state["tenant"]},
    )
    directory = app_connection.execute(text("SELECT * FROM auth.tenant_user_directory()"))
    row = directory.one()
    assert row.user_id == bootstrap_state["user"]
    assert row.membership_id == bootstrap_state["membership"]
    assert row.role_keys == ["tenant_admin"]
    event_id = app_connection.scalar(text("SELECT id FROM app.tenant_access_events"))
    assert event_id is not None
    assert not app_connection.scalar(
        text(
            "SELECT has_table_privilege(current_user,'app.tenant_access_events','UPDATE') "
            "OR has_table_privilege(current_user,'app.tenant_access_events','DELETE')"
        )
    )
    app_connection.execute(
        text("SELECT set_config('app.tenant_id',:tenant,true)"), {"tenant": uuid.uuid7()}
    )
    assert app_connection.execute(text("SELECT id FROM app.tenant_access_events")).all() == []


def test_bootstrap_capability_has_only_exact_function_execution(
    app_connection: Connection,
    application_role: str,
    migration_role: str,
    settings: Settings,
) -> None:
    capability = make_url(settings.required_identity_bootstrap_database_url).username
    assert capability == "sahl_identity_bootstrap_test"
    functions = (
        "auth.bootstrap_tenant_catalog()",
        "auth.bootstrap_tenant_admin(uuid,text,text,text,uuid,uuid,uuid)",
        "auth.admin_password_snapshot(text)",
        "auth.admin_apply_password_reset(uuid,bigint,bigint,text,boolean)",
    )
    for signature in functions:
        row = app_connection.execute(
            text(
                "SELECT p.prosecdef,pg_get_userbyid(p.proowner),p.proconfig,"
                "has_function_privilege(:capability,p.oid,'EXECUTE'),"
                "has_function_privilege('PUBLIC',p.oid,'EXECUTE'),"
                "has_function_privilege(:runtime,p.oid,'EXECUTE') "
                "FROM pg_proc p WHERE p.oid=CAST(:signature AS regprocedure)"
            ),
            {
                "capability": capability,
                "runtime": application_role,
                "signature": signature,
            },
        ).one()
        assert row == (True, migration_role, ["search_path=pg_catalog"], True, False, False)
    for table in (
        "auth.users",
        "auth.password_credentials",
        "auth.tenant_memberships",
        "auth.roles",
        "auth.role_permissions",
        "auth.membership_roles",
    ):
        assert not app_connection.scalar(
            text(
                "SELECT has_table_privilege(:capability,CAST(:table AS regclass),"
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')"
            ),
            {"capability": capability, "table": table},
        )
