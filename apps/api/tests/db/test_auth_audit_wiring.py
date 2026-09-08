# ruff: noqa: E501
"""G3 authentication audit proofs against an isolated real PostgreSQL database."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.audit.contracts import SecurityAuditEvent, SecurityEventType
from app.audit.writer import SecurityAuditWriteError, SecurityEventWriter
from app.auth.controls import PostgresThrottleStore, ThrottleScope, sensitive_key_digest
from app.auth.password_authentication import PasswordAuthenticationService
from app.auth.postgres import PostgresSessionStore
from app.auth.sessions import MAX_CONCURRENT_SESSIONS, IssuedSession, SessionService
from app.core.config import Settings
from app.security.passwords import PasswordService

PASSWORD = "g3 current test password 123"
NEW_PASSWORD = "g3 replacement test password 123"


class TransactionCheckedPasswords(PasswordService):
    def __init__(self, transactions: set[int]) -> None:
        super().__init__()
        self.transactions = transactions
        self.hash_calls = 0
        self.verify_calls = 0

    async def hash_password(self, password: str) -> str:
        assert not self.transactions, "Argon2 must not hold a database transaction."
        self.hash_calls += 1
        return await super().hash_password(password)

    async def verify_password(self, password_hash: str, password: str) -> bool:
        assert not self.transactions, "Argon2 must not hold a database transaction."
        self.verify_calls += 1
        return await super().verify_password(password_hash, password)


@dataclass
class AuthEventFixture:
    runtime: AsyncEngine
    migrator: Engine
    service: PasswordAuthenticationService
    passwords: TransactionCheckedPasswords
    user: uuid.UUID
    email: str
    ip: str
    initial_events: set[uuid.UUID]
    hmac_key: bytes = field(repr=False)

    def events(self) -> list:
        with self.migrator.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id,event_type,user_id,session_id,reason_code,correlation_id FROM auth.security_events ORDER BY created_at,id"
                )
            ).all()
        return [row for row in rows if row.id not in self.initial_events]

    async def issue(self) -> IssuedSession:
        async with self.runtime.begin() as connection:
            return await SessionService(PostgresSessionStore(connection)).issue(self.user, 1)


@pytest.fixture
async def auth_events(settings: Settings) -> AsyncIterator[AuthEventFixture]:
    runtime = create_async_engine(settings.database_url, poolclass=NullPool)
    migrator = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    transactions: set[int] = set()
    event.listen(runtime.sync_engine, "begin", lambda connection: transactions.add(id(connection)))
    event.listen(
        runtime.sync_engine, "commit", lambda connection: transactions.discard(id(connection))
    )
    event.listen(
        runtime.sync_engine, "rollback", lambda connection: transactions.discard(id(connection))
    )
    passwords = TransactionCheckedPasswords(transactions)
    user = uuid.uuid7()
    email = f"g3-audit-{user.hex}@example.test"
    ip = f"g3-audit-{user.hex}"
    hmac_key = secrets.token_bytes(32)
    password_hash = await passwords.hash_password(PASSWORD)
    with migrator.begin() as connection:
        initial = set(connection.scalars(text("SELECT id FROM auth.security_events")))
        connection.execute(
            text(
                "INSERT INTO auth.users(id,email,normalized_email,status) VALUES(:id,:email,:email,'active')"
            ),
            {"id": user, "email": email},
        )
        connection.execute(
            text("INSERT INTO auth.password_credentials(user_id,password_hash) VALUES(:id,:hash)"),
            {"id": user, "hash": password_hash},
        )
    data = AuthEventFixture(
        runtime,
        migrator,
        PasswordAuthenticationService(runtime, passwords, hmac_key),
        passwords,
        user,
        email,
        ip,
        initial,
        hmac_key,
    )
    try:
        yield data
    finally:
        await runtime.dispose()
        new_events = [row.id for row in data.events()]
        with migrator.begin() as connection:
            if new_events:
                connection.execute(
                    text("DELETE FROM auth.security_events WHERE id=ANY(:ids)"), {"ids": new_events}
                )
            connection.execute(text("DELETE FROM auth.sessions WHERE user_id=:id"), {"id": user})
            connection.execute(
                text("DELETE FROM auth.password_credentials WHERE user_id=:id"), {"id": user}
            )
            connection.execute(text("DELETE FROM auth.users WHERE id=:id"), {"id": user})
        migrator.dispose()


async def test_successful_login_has_one_trusted_event_and_no_argon_transaction(
    auth_events: AuthEventFixture,
) -> None:
    data = auth_events
    issued = await data.service.login(data.email, PASSWORD, data.ip)
    assert issued is not None
    events = data.events()
    assert [(row.event_type, row.user_id, row.session_id) for row in events] == [
        (SecurityEventType.LOGIN_SUCCESS.value, data.user, issued.record.id)
    ]
    assert data.passwords.verify_calls == 1
    assert data.passwords.hash_calls == 2  # Fixture credential and non-authority dummy workload.


@pytest.mark.parametrize("kind", ["wrong_password", "missing_user", "suspended_user"])
async def test_login_failure_has_one_anonymous_event_and_identical_throttle_scopes(
    auth_events: AuthEventFixture, kind: str
) -> None:
    data = auth_events
    email = data.email
    password = PASSWORD
    if kind == "wrong_password":
        password = "g3 definitely incorrect password"
    elif kind == "missing_user":
        email = f"missing-{data.user.hex}@example.test"
    else:
        with data.migrator.begin() as owner_connection:
            owner_connection.execute(
                text("UPDATE auth.users SET status='suspended' WHERE id=:id"), {"id": data.user}
            )
    assert await data.service.login(email, password, data.ip) is None
    assert [(row.event_type, row.user_id, row.session_id) for row in data.events()] == [
        (SecurityEventType.LOGIN_FAILURE.value, None, None)
    ]
    assert data.passwords.verify_calls == 1
    with data.migrator.connect() as owner_connection:
        for scope, value in (
            (ThrottleScope.LOGIN_USERNAME, email),
            (ThrottleScope.LOGIN_IP, data.ip),
            (ThrottleScope.LOGIN_IP_USERNAME, data.ip + "\0" + email),
        ):
            assert (
                owner_connection.scalar(
                    text(
                        "SELECT request_count FROM auth.throttle_buckets WHERE scope=:scope AND key_digest=:digest"
                    ),
                    {
                        "scope": scope.value,
                        "digest": sensitive_key_digest(data.hmac_key, scope, value),
                    },
                )
                == 1
            )


async def test_login_event_failure_rolls_back_session_issuance(
    auth_events: AuthEventFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(self: SecurityEventWriter, audit_event: SecurityAuditEvent) -> None:
        if audit_event.event_type is SecurityEventType.LOGIN_SUCCESS:
            raise SecurityAuditWriteError()

    monkeypatch.setattr(SecurityEventWriter, "write", fail)
    data = auth_events
    with pytest.raises(SecurityAuditWriteError):
        await data.service.login(data.email, PASSWORD, data.ip)
    with data.migrator.connect() as owner_connection:
        assert (
            owner_connection.scalar(
                text("SELECT count(*) FROM auth.sessions WHERE user_id=:id"), {"id": data.user}
            )
            == 0
        )
    assert not data.events()


@pytest.mark.parametrize("change", ["credential", "status", "security_version"])
async def test_login_rechecks_current_authority_after_argon(
    auth_events: AuthEventFixture, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    data = auth_events
    original = data.passwords.verify_password

    async def verify(password_hash: str, password: str) -> bool:
        verified = await original(password_hash, password)
        with data.migrator.begin() as owner_connection:
            if change == "credential":
                sql = "UPDATE auth.password_credentials SET credential_version=credential_version+1 WHERE user_id=:id"
            elif change == "status":
                sql = "UPDATE auth.users SET status='suspended' WHERE id=:id"
            else:
                sql = "UPDATE auth.users SET security_version=security_version+1 WHERE id=:id"
            owner_connection.execute(text(sql), {"id": data.user})
        return verified

    monkeypatch.setattr(data.passwords, "verify_password", verify)
    assert await data.service.login(data.email, PASSWORD, data.ip) is None
    assert [row.event_type for row in data.events()] == [SecurityEventType.LOGIN_FAILURE.value]


async def test_password_change_emits_once_and_invalidates_sessions(
    auth_events: AuthEventFixture,
) -> None:
    data = auth_events
    issued = await data.issue()
    assert await data.service.change_password(issued.secrets.bearer, PASSWORD, NEW_PASSWORD)
    rows = data.events()
    assert sorted(row.event_type for row in rows) == [
        SecurityEventType.ALL_SESSIONS_REVOKED.value,
        SecurityEventType.PASSWORD_CHANGED.value,
    ]
    assert {row.user_id for row in rows} == {data.user}
    assert len({row.correlation_id for row in rows}) == 1
    assert not await data.service.change_password(issued.secrets.bearer, NEW_PASSWORD, PASSWORD)
    assert len(data.events()) == 2
    with data.migrator.connect() as owner_connection:
        row = owner_connection.execute(
            text(
                "SELECT c.password_hash,c.credential_version,u.security_version,s.revoked_at FROM auth.password_credentials c JOIN auth.users u ON u.id=c.user_id JOIN auth.sessions s ON s.user_id=u.id WHERE u.id=:id"
            ),
            {"id": data.user},
        ).one()
    assert row.credential_version == row.security_version == 2 and row.revoked_at is not None
    assert await data.passwords.verify_password(row.password_hash, NEW_PASSWORD)
    assert not await data.passwords.verify_password(row.password_hash, PASSWORD)
    assert await data.service.login(data.email, PASSWORD, data.ip) is None
    assert await data.service.login(data.email, NEW_PASSWORD, data.ip) is not None


@pytest.mark.parametrize(
    "operation", ["logout", "revoke_current", "revoke_all", "concurrent_limit"]
)
async def test_session_mutation_event_failure_rolls_back(
    auth_events: AuthEventFixture, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    data = auth_events
    issued = await data.issue()
    if operation == "concurrent_limit":
        for _ in range(MAX_CONCURRENT_SESSIONS - 1):
            await data.issue()

    async def fail(self: SecurityEventWriter, audit_event: SecurityAuditEvent) -> None:
        raise SecurityAuditWriteError()

    monkeypatch.setattr(SecurityEventWriter, "write", fail)
    with pytest.raises(SecurityAuditWriteError):
        async with data.runtime.begin() as connection:
            sessions = SessionService(PostgresSessionStore(connection))
            if operation == "revoke_all":
                await sessions.revoke_all(data.user)
            elif operation == "concurrent_limit":
                await sessions.issue(data.user, 1)
            else:
                await getattr(sessions, operation)(issued.secrets.bearer)
    with data.migrator.connect() as owner_connection:
        assert (
            owner_connection.scalar(
                text(
                    "SELECT count(*) FROM auth.sessions WHERE user_id=:id AND revoked_at IS NOT NULL"
                ),
                {"id": data.user},
            )
            == 0
        )
    assert not data.events()


@pytest.mark.parametrize("scope", list(ThrottleScope))
async def test_denied_throttle_has_one_event_in_counter_transaction(
    auth_events: AuthEventFixture, scope: ThrottleScope
) -> None:
    data = auth_events
    digest = sensitive_key_digest(data.hmac_key, scope, data.ip)
    async with data.runtime.begin() as connection:
        store = PostgresThrottleStore(connection)
        assert (await store.consume(scope, digest, 1, 1, 60)).allowed
        assert not (await store.consume(scope, digest, 1, 1, 60)).allowed
    assert [row.event_type for row in data.events()] == [
        SecurityEventType.THROTTLING_TRIGGERED.value
    ]


async def test_password_change_event_failure_rolls_back_every_mutation(
    auth_events: AuthEventFixture,
) -> None:
    from app.auth.password_authentication import PasswordAuthenticationUnavailableError

    data = auth_events
    issued = await data.issue()
    constraint = "g3_test_password_event_failure"
    with data.migrator.begin() as owner_connection:
        owner_connection.execute(
            text(
                f"ALTER TABLE auth.security_events ADD CONSTRAINT {constraint} CHECK (event_type<>'password_changed') NOT VALID"
            )
        )
    try:
        with pytest.raises(PasswordAuthenticationUnavailableError) as error:
            await data.service.change_password(issued.secrets.bearer, PASSWORD, NEW_PASSWORD)
        assert PASSWORD not in str(error.value) and NEW_PASSWORD not in str(error.value)
        with data.migrator.connect() as owner_connection:
            row = owner_connection.execute(
                text(
                    "SELECT c.credential_version,u.security_version,s.revoked_at FROM auth.password_credentials c JOIN auth.users u ON u.id=c.user_id JOIN auth.sessions s ON s.user_id=u.id WHERE u.id=:id"
                ),
                {"id": data.user},
            ).one()
        assert row.credential_version == row.security_version == 1
        assert row.revoked_at is None
        assert not data.events()
    finally:
        with data.migrator.begin() as owner_connection:
            owner_connection.execute(
                text(f"ALTER TABLE auth.security_events DROP CONSTRAINT {constraint}")
            )


async def test_denied_throttle_event_failure_rolls_back_counter(
    auth_events: AuthEventFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = auth_events
    digest = sensitive_key_digest(data.hmac_key, ThrottleScope.LOGIN_IP, data.ip)
    async with data.runtime.begin() as connection:
        assert (
            await PostgresThrottleStore(connection).consume(
                ThrottleScope.LOGIN_IP, digest, 1, 1, 60
            )
        ).allowed

    async def fail(self: SecurityEventWriter, audit_event: SecurityAuditEvent) -> None:
        raise SecurityAuditWriteError()

    monkeypatch.setattr(SecurityEventWriter, "write", fail)
    with pytest.raises(SecurityAuditWriteError):
        async with data.runtime.begin() as connection:
            await PostgresThrottleStore(connection).consume(
                ThrottleScope.LOGIN_IP, digest, 1, 1, 60
            )
    with data.migrator.connect() as owner_connection:
        assert (
            owner_connection.scalar(
                text(
                    "SELECT request_count FROM auth.throttle_buckets WHERE scope='login_ip' AND key_digest=:digest"
                ),
                {"digest": digest},
            )
            == 1
        )


async def test_password_authentication_functions_have_only_narrow_runtime_grants(
    auth_events: AuthEventFixture,
) -> None:
    data = auth_events
    names = [
        "password_authentication_snapshot",
        "password_change_snapshot",
        "confirm_password_authentication",
        "apply_password_change",
    ]
    async with data.runtime.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT p.proname,pg_get_userbyid(p.proowner),p.prosecdef,p.proconfig,has_function_privilege(current_user,p.oid,'EXECUTE'),has_function_privilege('public',p.oid,'EXECUTE'),pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='auth' AND p.proname=ANY(:names)"
                ),
                {"names": names},
            )
        ).all()
        assert len(rows) == 4
        for _, owner, security_definer, config, app_execute, public_execute, definition in rows:
            assert (owner, security_definer, config, app_execute, public_execute) == (
                "sahl_migrator",
                True,
                ["search_path=pg_catalog"],
                True,
                False,
            )
            assert "EXECUTE " not in definition.upper()
        for table in ("auth.users", "auth.password_credentials", "auth.security_events"):
            assert not await connection.scalar(
                text(
                    "SELECT has_table_privilege(current_user,:table,'SELECT,INSERT,UPDATE,DELETE')"
                ),
                {"table": table},
            )


@pytest.mark.parametrize(
    "operation", ["logout", "revoke_current", "revoke_all", "concurrent_limit"]
)
async def test_session_mutation_success_has_exactly_one_event(
    auth_events: AuthEventFixture, operation: str
) -> None:
    data = auth_events
    issued = await data.issue()
    if operation == "concurrent_limit":
        for _ in range(MAX_CONCURRENT_SESSIONS - 1):
            await data.issue()
    async with data.runtime.begin() as connection:
        sessions = SessionService(PostgresSessionStore(connection))
        if operation == "revoke_all":
            assert await sessions.revoke_all(data.user) == 1
            assert await sessions.revoke_all(data.user) == 0
        elif operation == "concurrent_limit":
            await sessions.issue(data.user, 1)
        else:
            assert await getattr(sessions, operation)(issued.secrets.bearer)
            assert not await getattr(sessions, operation)(issued.secrets.bearer)
    expected = {
        "logout": SecurityEventType.LOGOUT,
        "revoke_current": SecurityEventType.SESSION_REVOKED,
        "revoke_all": SecurityEventType.ALL_SESSIONS_REVOKED,
        "concurrent_limit": SecurityEventType.SESSION_REVOKED,
    }[operation]
    assert [row.event_type for row in data.events()] == [expected.value]


@pytest.mark.parametrize("change", ["session_revoked", "session_rotated", "credential"])
async def test_password_change_rechecks_after_hash_work(
    auth_events: AuthEventFixture, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    data = auth_events
    issued = await data.issue()
    original = data.passwords.hash_password

    async def hash_password(password: str) -> str:
        hashed = await original(password)
        if password == NEW_PASSWORD:
            with data.migrator.begin() as owner_connection:
                if change == "credential":
                    owner_connection.execute(
                        text(
                            "UPDATE auth.password_credentials SET credential_version=credential_version+1 WHERE user_id=:id"
                        ),
                        {"id": data.user},
                    )
                elif change == "session_revoked":
                    owner_connection.execute(
                        text(
                            "UPDATE auth.sessions SET revoked_at=clock_timestamp(),revoked_reason='revoke_all' WHERE id=:id"
                        ),
                        {"id": issued.record.id},
                    )
                else:
                    owner_connection.execute(
                        text("UPDATE auth.sessions SET bearer_digest=:digest WHERE id=:id"),
                        {"id": issued.record.id, "digest": secrets.token_bytes(32)},
                    )
        return hashed

    monkeypatch.setattr(data.passwords, "hash_password", hash_password)
    assert not await data.service.change_password(issued.secrets.bearer, PASSWORD, NEW_PASSWORD)
    assert not data.events()
    with data.migrator.connect() as owner_connection:
        row = owner_connection.execute(
            text(
                "SELECT c.password_hash,u.security_version FROM auth.password_credentials c JOIN auth.users u ON u.id=c.user_id WHERE u.id=:id"
            ),
            {"id": data.user},
        ).one()
    assert row.security_version == 1
    assert await data.passwords.verify_password(row.password_hash, PASSWORD)
