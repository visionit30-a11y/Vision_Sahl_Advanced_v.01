"""G4 session lifecycle, bearer, CSRF, and pre-auth contracts."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

from app.auth.sessions import (
    ABSOLUTE_TIMEOUT,
    IDLE_TIMEOUT,
    MAX_CONCURRENT_SESSIONS,
    MemorySessionStore,
    SessionService,
    token_digest,
    token_matches,
)

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


async def test_session_issuance_has_256_bit_opaque_bearer_and_digest_only_store() -> None:
    store = MemorySessionStore()
    issued = await SessionService(store).issue(uuid.uuid4(), 1, now=NOW)
    padded = issued.secrets.bearer + "=" * (-len(issued.secrets.bearer) % 4)
    assert len(base64.urlsafe_b64decode(padded)) == 32
    assert len(issued.record.bearer_digest) == 32
    assert issued.secrets.bearer.encode() not in issued.record.bearer_digest
    assert issued.secrets.bearer not in repr(issued) and issued.secrets.csrf_token not in repr(
        issued
    )


async def test_invalid_expired_revoked_and_security_version_sessions_fail() -> None:
    store = MemorySessionStore()
    service = SessionService(store)
    issued = await service.issue(uuid.uuid4(), 3, now=NOW)
    assert await service.resolve("invalid-bearer", 3, now=NOW) is None
    assert await service.resolve(issued.secrets.bearer, 4, now=NOW) is None
    assert await service.resolve(issued.secrets.bearer, 3, now=NOW + IDLE_TIMEOUT) is None
    issued2 = await service.issue(uuid.uuid4(), 1, now=NOW)
    assert await service.resolve(issued2.secrets.bearer, 1, now=NOW + ABSOLUTE_TIMEOUT) is None
    assert await service.logout(issued.secrets.bearer, now=NOW) is True
    assert await service.resolve(issued.secrets.bearer, 3, now=NOW) is None


async def test_last_seen_is_rate_limited_and_never_extends_absolute_timeout() -> None:
    service = SessionService(MemorySessionStore())
    issued = await service.issue(uuid.uuid4(), 1, now=NOW)
    unchanged = await service.resolve(issued.secrets.bearer, 1, now=NOW + timedelta(seconds=59))
    assert unchanged is not None and unchanged.last_seen_at == NOW
    touched = await service.resolve(issued.secrets.bearer, 1, now=NOW + timedelta(seconds=60))
    assert touched is not None and touched.last_seen_at == NOW + timedelta(seconds=60)
    assert touched.idle_expires_at <= touched.absolute_expires_at


async def test_logout_revoke_current_and_revoke_all() -> None:
    user = uuid.uuid4()
    service = SessionService(MemorySessionStore())
    first = await service.issue(user, 1, now=NOW)
    second = await service.issue(user, 1, now=NOW)
    assert await service.revoke_current(first.secrets.bearer, now=NOW) is True
    assert await service.revoke_current(first.secrets.bearer, now=NOW) is False
    assert await service.revoke_all(user, now=NOW) == 1
    assert await service.resolve(second.secrets.bearer, 1, now=NOW) is None


async def test_concurrent_limit_revokes_oldest_deterministically() -> None:
    store = MemorySessionStore()
    service = SessionService(store)
    user = uuid.uuid4()
    issued = []
    for offset in range(MAX_CONCURRENT_SESSIONS + 1):
        issued.append(await service.issue(user, 1, now=NOW + timedelta(seconds=offset)))
    assert (
        await service.resolve(issued[0].secrets.bearer, 1, now=NOW + timedelta(seconds=6)) is None
    )
    assert sum(item.revoked_reason == "concurrent_limit" for item in store.sessions.values()) == 1


async def test_rotation_invalidates_old_bearer_and_rotates_csrf() -> None:
    service = SessionService(MemorySessionStore())
    issued = await service.issue(uuid.uuid4(), 1, now=NOW)
    rotated = await service.rotate(issued.secrets.bearer, 1, now=NOW + timedelta(seconds=1))
    assert rotated is not None
    assert rotated.secrets.bearer != issued.secrets.bearer
    assert rotated.secrets.csrf_token != issued.secrets.csrf_token
    assert await service.resolve(issued.secrets.bearer, 1, now=NOW + timedelta(seconds=2)) is None
    assert (
        await service.resolve(rotated.secrets.bearer, 1, now=NOW + timedelta(seconds=2)) is not None
    )


async def test_csrf_is_bound_to_one_session() -> None:
    service = SessionService(MemorySessionStore())
    first = await service.issue(uuid.uuid4(), 1, now=NOW)
    second = await service.issue(uuid.uuid4(), 1, now=NOW)
    assert token_matches(first.secrets.csrf_token, first.record.csrf_digest)
    assert not token_matches(second.secrets.csrf_token, first.record.csrf_digest)


async def test_preauth_csrf_is_single_use_and_expires() -> None:
    service = SessionService(MemorySessionStore())
    issued = await service.issue_preauth(now=NOW)
    assert await service.consume_preauth(issued.state_token, "wrong-csrf-token", now=NOW) is False
    assert await service.consume_preauth(issued.state_token, issued.csrf_token, now=NOW) is True
    assert await service.consume_preauth(issued.state_token, issued.csrf_token, now=NOW) is False
    expired = await service.issue_preauth(now=NOW)
    assert (
        await service.consume_preauth(
            expired.state_token, expired.csrf_token, now=NOW + timedelta(minutes=10)
        )
        is False
    )


def test_digest_is_sha256_and_repr_never_contains_secrets() -> None:
    assert len(token_digest("opaque")) == 32
