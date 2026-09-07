"""Live PostgreSQL proof for the narrow trusted-membership bootstrap boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Connection, Row, create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import Settings

FUNCTION = "auth.resolve_active_membership(uuid,uuid,integer,integer)"


def _resolve(
    connection: Connection,
    user: uuid.UUID,
    membership: uuid.UUID,
    version: int | None = 1,
    security_version: int = 1,
) -> Row[tuple[uuid.UUID, uuid.UUID, int]] | None:
    return connection.execute(
        text("""
        SELECT * FROM auth.resolve_active_membership(:user,:membership,:version,:security)
    """),
        {"user": user, "membership": membership, "version": version, "security": security_version},
    ).one_or_none()


def test_bootstrap_function_security_contract(
    app_connection: Connection, migration_role: str, application_role: str
) -> None:
    row = app_connection.execute(
        text("""
        SELECT p.prosecdef, pg_get_userbyid(p.proowner), p.proconfig,
          has_function_privilege(:app,p.oid,'EXECUTE') AS app_may_execute,
          has_function_privilege('public',p.oid,'EXECUTE') AS public_may_execute,
          pg_get_functiondef(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='auth' AND p.proname='resolve_active_membership'
    """),
        {"app": application_role},
    ).one()
    assert row.prosecdef is True and row.pg_get_userbyid == migration_role
    assert row.proconfig == ["search_path=pg_catalog"]
    assert row.app_may_execute is True
    assert row.public_may_execute is False
    assert "EXECUTE" not in row.pg_get_functiondef.upper()
    assert "SET_CONFIG" not in row.pg_get_functiondef.upper()


def test_runtime_has_no_direct_select_on_memberships_or_tenants(app_connection: Connection) -> None:
    assert (
        app_connection.scalar(
            text("SELECT has_table_privilege(current_user,'auth.tenant_memberships','SELECT')")
        )
        is False
    )
    assert (
        app_connection.scalar(
            text("SELECT has_table_privilege(current_user,'public.tenants','SELECT')")
        )
        is False
    )


def test_function_accepts_only_active_owned_current_membership(
    app_connection: Connection, settings: Settings
) -> None:
    user, other, tenant, membership = uuid.uuid7(), uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    now = datetime.now(UTC)
    slug = f"g5-{tenant.hex[:16]}"
    engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO public.tenants(id,slug,name_ar,name_en,status) "
                "VALUES (:id,:slug,'اختبار','test','active')"
            ),
            {"id": tenant, "slug": slug},
        )
        for identity in (user, other):
            email = f"g5-{identity.hex}@example.test"
            db.execute(
                text(
                    "INSERT INTO auth.users(id,email,normalized_email,status) "
                    "VALUES (:id,:email,:email,'active')"
                ),
                {"id": identity, "email": email},
            )
        db.execute(
            text("""
            INSERT INTO auth.tenant_memberships(id,user_id,tenant_id,status,joined_at)
            VALUES (:id,:user,:tenant,'active',:now)
        """),
            {"id": membership, "user": user, "tenant": tenant, "now": now},
        )
    result = _resolve(app_connection, user, membership)
    assert result is not None and tuple(result) == (tenant, membership, 1)
    assert _resolve(app_connection, other, membership) is None
    assert _resolve(app_connection, user, uuid.uuid7()) is None
    assert _resolve(app_connection, user, membership, version=2) is None
    for statement in (
        "UPDATE auth.tenant_memberships SET status='suspended' WHERE id=:id",
        "UPDATE auth.tenant_memberships SET status='left',left_at=now() WHERE id=:id",
        "UPDATE auth.users SET status='suspended' WHERE id=:user",
        "UPDATE public.tenants SET status='suspended' WHERE id=:tenant",
    ):
        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE auth.tenant_memberships SET status='active',left_at=NULL WHERE id=:id"
                ),
                {"id": membership},
            )
            db.execute(text("UPDATE auth.users SET status='active' WHERE id=:user"), {"user": user})
            db.execute(
                text("UPDATE public.tenants SET status='active' WHERE id=:tenant"),
                {"tenant": tenant},
            )
            db.execute(text(statement), {"id": membership, "user": user, "tenant": tenant})
        assert _resolve(app_connection, user, membership) is None
    app_connection.rollback()
    with engine.begin() as db:
        db.execute(text("DELETE FROM auth.tenant_memberships WHERE id=:id"), {"id": membership})
        db.execute(
            text("DELETE FROM auth.users WHERE id IN (:user,:other)"),
            {"user": user, "other": other},
        )
        db.execute(text("DELETE FROM public.tenants WHERE id=:tenant"), {"tenant": tenant})
    engine.dispose()


def test_session_selection_columns_and_composite_fk_exist(app_connection: Connection) -> None:
    columns = set(
        app_connection.execute(
            text("""
        SELECT attname FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='auth'
          AND c.relname='sessions' AND a.attnum>0 AND NOT a.attisdropped
    """)
        ).scalars()
    )
    assert {"selected_membership_id", "selected_membership_version"} <= columns
    constraints = set(
        app_connection.execute(
            text("""
        SELECT conname FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='auth' AND c.relname='sessions'
    """)
        ).scalars()
    )
    assert {
        "fk_sessions_selected_membership_id_tenant_memberships",
        "ck_sessions_selected_membership_pair",
    } <= constraints
