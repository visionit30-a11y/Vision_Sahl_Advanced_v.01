# ruff: noqa: E501
"""Live PostgreSQL proofs for G6 throttles, reset tokens, and security events."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from app.auth.controls import ThrottleScope, sensitive_key_digest, token_digest
from app.auth.sessions import token_digest as session_digest
from app.core.config import Settings
from app.security.passwords import PasswordService

PASSWORD = "existing password 123"
NEW_PASSWORD = "replacement password 123"


def _consume(url: str, digest: bytes, limit: int = 5) -> tuple[bool, int]:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text("""SELECT * FROM auth.consume_throttle(
                CAST('login_ip' AS text),CAST(:key AS bytea),CAST(1 AS smallint),
                CAST(:limit AS integer),CAST(900 AS integer)
                )"""),
                {"key": digest, "limit": limit},
            ).one()
            return bool(row.allowed), int(row.request_count)
    finally:
        engine.dispose()


def test_throttle_increment_and_limit_are_atomic_under_concurrency(settings: Settings) -> None:
    digest = sensitive_key_digest(b"g6-test-key" * 4, ThrottleScope.LOGIN_IP, uuid.uuid4().hex)
    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(
            executor.map(
                lambda _: _consume(settings.database_url, digest),
                range(12),
            )
        )
    assert sorted(count for _, count in results) == list(range(1, 13))
    assert sum(allowed for allowed, _ in results) == 5


def test_security_tables_have_no_direct_runtime_or_public_grants(
    app_connection: Connection, migration_role: str, application_role: str
) -> None:
    tables = ("password_reset_tokens", "security_events", "throttle_buckets")
    rows = app_connection.execute(
        text("""
        SELECT c.relname,pg_get_userbyid(c.relowner),
          has_table_privilege(:role,c.oid,'SELECT,INSERT,UPDATE,DELETE')
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='auth' AND c.relname=ANY(:tables) ORDER BY c.relname
        """),
        {"role": application_role, "tables": list(tables)},
    ).all()
    assert rows == [(name, migration_role, False) for name in sorted(tables)]
    assert (
        app_connection.scalar(
            text("""
        SELECT count(*) FROM information_schema.role_table_grants
        WHERE table_schema='auth' AND table_name=ANY(:tables) AND grantee='PUBLIC'
        """),
            {"tables": list(tables)},
        )
        == 0
    )


def test_g6_functions_are_narrow_security_definers(
    app_connection: Connection, migration_role: str, application_role: str
) -> None:
    rows = app_connection.execute(
        text("""
        SELECT p.proname,pg_get_userbyid(p.proowner),p.prosecdef,p.proconfig,
          has_function_privilege(:role,p.oid,'EXECUTE'),
          has_function_privilege('public',p.oid,'EXECUTE'),pg_get_functiondef(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='auth' AND p.proname=ANY(:names) ORDER BY p.proname
        """),
        {
            "role": application_role,
            "names": [
                "complete_password_reset",
                "consume_throttle",
                "record_security_event",
                "request_password_reset",
            ],
        },
    ).all()
    assert len(rows) == 4
    for _, owner, security_definer, config, app_execute, public_execute, definition in rows:
        assert (owner, security_definer, app_execute, public_execute) == (
            migration_role,
            True,
            True,
            False,
        )
        assert config == ["search_path=pg_catalog"]
        assert "EXECUTE " not in definition.upper()


async def test_reset_lifecycle_is_atomic_and_invalidates_credentials_and_sessions(
    app_connection: Connection, settings: Settings
) -> None:
    passwords = PasswordService()
    old_hash = await passwords.hash_password(PASSWORD)
    new_hash = await passwords.hash_password(NEW_PASSWORD)
    user_id, session_id = uuid.uuid7(), uuid.uuid7()
    email = f"g6-{user_id.hex}@example.test"
    raw_token, second_token = uuid.uuid4().hex * 2, uuid.uuid4().hex * 2
    migration = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    try:
        with migration.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO auth.users(id,email,normalized_email,status) VALUES(:id,:e,:e,'active')"
                ),
                {"id": user_id, "e": email},
            )
            connection.execute(
                text("INSERT INTO auth.password_credentials(user_id,password_hash) VALUES(:id,:h)"),
                {"id": user_id, "h": old_hash},
            )
            now = datetime.now(UTC)
            connection.execute(
                text("""
                INSERT INTO auth.sessions(id,user_id,bearer_digest,csrf_digest,security_version,
                  created_at,authenticated_at,last_seen_at,idle_expires_at,absolute_expires_at)
                VALUES(:sid,:uid,:b,:c,1,:n,:n,:n,:idle,:absolute)
                """),
                {
                    "sid": session_id,
                    "uid": user_id,
                    "b": session_digest(f"old bearer {session_id}"),
                    "c": session_digest(f"old csrf {session_id}"),
                    "n": now,
                    "idle": now + timedelta(minutes=30),
                    "absolute": now + timedelta(hours=8),
                },
            )
        first_id, second_id = uuid.uuid7(), uuid.uuid7()
        assert (
            app_connection.scalar(
                text("SELECT auth.request_password_reset(:e,:d,:t,:v,'corr-1')"),
                {"e": email, "d": token_digest(raw_token), "t": first_id, "v": uuid.uuid7()},
            )
            is True
        )
        app_connection.commit()
        assert (
            app_connection.scalar(
                text("SELECT auth.request_password_reset(:e,:d,:t,:v,'corr-2')"),
                {"e": email, "d": token_digest(second_token), "t": second_id, "v": uuid.uuid7()},
            )
            is True
        )
        app_connection.commit()
        with migration.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT revoked_at IS NOT NULL FROM auth.password_reset_tokens WHERE id=:id"
                    ),
                    {"id": first_id},
                )
                is True
            )
        assert (
            app_connection.scalar(
                text("SELECT auth.complete_password_reset(:d,:h,:v,'corr-3')"),
                {"d": token_digest(second_token), "h": new_hash, "v": uuid.uuid7()},
            )
            is True
        )
        app_connection.commit()
        assert (
            app_connection.scalar(
                text("SELECT auth.complete_password_reset(:d,:h,:v,'corr-4')"),
                {"d": token_digest(second_token), "h": old_hash, "v": uuid.uuid7()},
            )
            is False
        )
        app_connection.rollback()
        with migration.connect() as connection:
            credential = connection.execute(
                text(
                    "SELECT password_hash,credential_version FROM auth.password_credentials WHERE user_id=:id"
                ),
                {"id": user_id},
            ).one()
            assert credential.credential_version == 2
            assert await passwords.verify_password(credential.password_hash, NEW_PASSWORD)
            assert not await passwords.verify_password(credential.password_hash, PASSWORD)
            assert (
                connection.scalar(
                    text("SELECT security_version FROM auth.users WHERE id=:id"), {"id": user_id}
                )
                == 2
            )
            assert (
                connection.scalar(
                    text("SELECT revoked_reason FROM auth.sessions WHERE id=:id"),
                    {"id": session_id},
                )
                == "password_reset"
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM auth.security_events WHERE user_id=:id"),
                    {"id": user_id},
                )
                == 3
            )
    finally:
        with migration.begin() as connection:
            connection.execute(
                text("DELETE FROM auth.password_credentials WHERE user_id=:id"), {"id": user_id}
            )
            connection.execute(text("DELETE FROM auth.users WHERE id=:id"), {"id": user_id})
        migration.dispose()


def test_nonexistent_reset_is_indistinguishable_at_database_boundary(
    app_connection: Connection,
) -> None:
    digest = token_digest(uuid.uuid4().hex * 2)
    assert (
        app_connection.scalar(
            text("SELECT auth.request_password_reset(:e,:d,:t,:v,'correlation')"),
            {
                "e": f"missing-{uuid.uuid4().hex}@example.test",
                "d": digest,
                "t": uuid.uuid7(),
                "v": uuid.uuid7(),
            },
        )
        is False
    )
    app_connection.rollback()


async def test_reset_token_concurrent_use_has_exactly_one_winner(settings: Settings) -> None:
    passwords = PasswordService()
    old_hash = await passwords.hash_password(PASSWORD)
    new_hash = await passwords.hash_password(NEW_PASSWORD)
    user_id, token_id = uuid.uuid7(), uuid.uuid7()
    raw = uuid.uuid4().hex * 2
    migration = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    app = create_engine(settings.database_url, poolclass=NullPool)
    try:
        with migration.begin() as connection:
            email = f"race-{user_id.hex}@example.test"
            connection.execute(
                text(
                    "INSERT INTO auth.users(id,email,normalized_email,status) VALUES(:id,:e,:e,'active')"
                ),
                {"id": user_id, "e": email},
            )
            connection.execute(
                text("INSERT INTO auth.password_credentials(user_id,password_hash) VALUES(:id,:h)"),
                {"id": user_id, "h": old_hash},
            )
            connection.execute(
                text("""
                INSERT INTO auth.password_reset_tokens(id,user_id,token_digest,created_at,expires_at)
                VALUES(:id,:user,:digest,clock_timestamp(),clock_timestamp()+interval '15 minutes')
                """),
                {"id": token_id, "user": user_id, "digest": token_digest(raw)},
            )

        def complete() -> bool:
            with app.begin() as connection:
                return bool(
                    connection.scalar(
                        text("SELECT auth.complete_password_reset(:d,:h,:v,'race')"),
                        {"d": token_digest(raw), "h": new_hash, "v": uuid.uuid7()},
                    )
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: complete(), range(2)))
        assert sorted(results) == [False, True]
    finally:
        app.dispose()
        with migration.begin() as connection:
            connection.execute(
                text("DELETE FROM auth.password_credentials WHERE user_id=:id"), {"id": user_id}
            )
            connection.execute(text("DELETE FROM auth.users WHERE id=:id"), {"id": user_id})
        migration.dispose()


async def test_mandatory_event_failure_rolls_back_reset(settings: Settings) -> None:
    passwords = PasswordService()
    old_hash = await passwords.hash_password(PASSWORD)
    new_hash = await passwords.hash_password(NEW_PASSWORD)
    user_id, token_id, event_id = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    raw = uuid.uuid4().hex * 2
    migration = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    app = create_engine(settings.database_url, poolclass=NullPool)
    try:
        with migration.begin() as connection:
            email = f"rollback-{user_id.hex}@example.test"
            connection.execute(
                text(
                    "INSERT INTO auth.users(id,email,normalized_email,status) VALUES(:id,:e,:e,'active')"
                ),
                {"id": user_id, "e": email},
            )
            connection.execute(
                text("INSERT INTO auth.password_credentials(user_id,password_hash) VALUES(:id,:h)"),
                {"id": user_id, "h": old_hash},
            )
            connection.execute(
                text("""
                INSERT INTO auth.password_reset_tokens(id,user_id,token_digest,created_at,expires_at)
                VALUES(:id,:user,:digest,clock_timestamp(),clock_timestamp()+interval '15 minutes')
                """),
                {"id": token_id, "user": user_id, "digest": token_digest(raw)},
            )
            connection.execute(
                text("""
                INSERT INTO auth.security_events(id,event_type,result,correlation_id,created_at)
                VALUES(:id,'login_failure','failure','seed',clock_timestamp())
                """),
                {"id": event_id},
            )
        with pytest.raises(IntegrityError), app.begin() as connection:
            connection.execute(
                text("SELECT auth.complete_password_reset(:d,:h,:v,'duplicate')"),
                {"d": token_digest(raw), "h": new_hash, "v": event_id},
            )
        with migration.connect() as connection:
            row = connection.execute(
                text("""
                SELECT t.consumed_at,c.credential_version FROM auth.password_reset_tokens t
                JOIN auth.password_credentials c ON c.user_id=t.user_id WHERE t.id=:id
                """),
                {"id": token_id},
            ).one()
            assert row.consumed_at is None and row.credential_version == 1
    finally:
        app.dispose()
        with migration.begin() as connection:
            connection.execute(
                text("DELETE FROM auth.password_credentials WHERE user_id=:id"), {"id": user_id}
            )
            connection.execute(text("DELETE FROM auth.users WHERE id=:id"), {"id": user_id})
            connection.execute(
                text("DELETE FROM auth.security_events WHERE id=:id"), {"id": event_id}
            )
        migration.dispose()
