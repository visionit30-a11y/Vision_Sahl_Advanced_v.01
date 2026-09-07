"""Live PostgreSQL contract for G4 server-side session storage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.pool import NullPool

from app.auth.sessions import token_digest
from app.core.config import Settings


def test_session_tables_are_migrator_owned_with_precise_runtime_grants(
    app_connection: Connection, migration_role: str, application_role: str
) -> None:
    rows = app_connection.execute(
        text("""
        SELECT c.relname, pg_get_userbyid(c.relowner),
          has_table_privilege(:role,c.oid,'SELECT,INSERT,UPDATE'),
          has_table_privilege(:role,c.oid,'DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='auth' AND c.relname IN ('sessions','preauth_csrf_states')
        ORDER BY c.relname
    """),
        {"role": application_role},
    ).all()
    assert rows == [
        ("preauth_csrf_states", migration_role, True, False),
        ("sessions", migration_role, True, False),
    ]
    public = app_connection.scalar(
        text("""
        SELECT count(*) FROM information_schema.role_table_grants
        WHERE table_schema='auth' AND table_name IN ('sessions','preauth_csrf_states')
          AND grantee='PUBLIC'
    """)
    )
    assert public == 0


def test_runtime_persists_only_session_and_csrf_digests(
    app_connection: Connection, settings: Settings
) -> None:
    session_user = uuid.uuid4()
    email = f"g4-{session_user.hex}@example.test"
    migration_engine = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO auth.users (id,email,normalized_email,status) "
                "VALUES (:id,:email,:email,'active')"
            ),
            {"id": session_user, "email": email},
        )
    bearer = "raw-session-bearer-never-store"
    csrf = "raw-csrf-never-store"
    now = datetime.now(UTC)
    app_connection.execute(
        text("""
        INSERT INTO auth.sessions
          (id,user_id,bearer_digest,csrf_digest,security_version,created_at,authenticated_at,
           last_seen_at,idle_expires_at,absolute_expires_at)
        VALUES (:id,:user_id,:bearer,:csrf,1,:now,:now,:now,:idle,:absolute)
    """),
        {
            "id": uuid.uuid4(),
            "user_id": session_user,
            "bearer": token_digest(bearer),
            "csrf": token_digest(csrf),
            "now": now,
            "idle": now + timedelta(minutes=30),
            "absolute": now + timedelta(hours=8),
        },
    )
    stored = app_connection.execute(
        text("SELECT bearer_digest,csrf_digest FROM auth.sessions WHERE user_id=:id"),
        {"id": session_user},
    ).one()
    assert stored.bearer_digest == token_digest(bearer) and stored.csrf_digest == token_digest(csrf)
    assert bearer.encode() not in stored.bearer_digest and csrf.encode() not in stored.csrf_digest
    app_connection.rollback()
    with migration_engine.begin() as connection:
        connection.execute(text("DELETE FROM auth.users WHERE id=:id"), {"id": session_user})
    migration_engine.dispose()


def test_session_schema_has_no_tenant_or_raw_token_columns(app_connection: Connection) -> None:
    columns = set(
        app_connection.execute(
            text("""
        SELECT a.attname FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='auth' AND c.relname IN ('sessions','preauth_csrf_states')
          AND a.attnum>0 AND NOT a.attisdropped
    """)
        ).scalars()
    )
    assert "tenant_id" not in columns and "bearer" not in columns and "csrf_token" not in columns
    assert {
        "bearer_digest",
        "csrf_digest",
        "idle_expires_at",
        "absolute_expires_at",
        "revoked_at",
    } <= columns
