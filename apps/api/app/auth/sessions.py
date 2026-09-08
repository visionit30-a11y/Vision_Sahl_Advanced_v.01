"""Opaque PostgreSQL-backed session lifecycle domain."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.audit.contracts import (
    SecurityAuditEvent,
    SecurityEventResult,
    SecurityEventType,
    SecurityReasonCode,
)

BEARER_BYTES = 32
CSRF_BYTES = 32
IDLE_TIMEOUT = timedelta(minutes=30)
ABSOLUTE_TIMEOUT = timedelta(hours=8)
LAST_SEEN_INTERVAL = timedelta(seconds=60)
MAX_CONCURRENT_SESSIONS = 5
PREAUTH_LIFETIME = timedelta(minutes=10)


def _token(size: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(size)).rstrip(b"=").decode("ascii")


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def token_matches(token: str, digest: bytes) -> bool:
    return hmac.compare_digest(token_digest(token), digest)


@dataclass(frozen=True, slots=True)
class SessionSecrets:
    bearer: str = field(repr=False)
    csrf_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: uuid.UUID
    user_id: uuid.UUID
    bearer_digest: bytes = field(repr=False)
    csrf_digest: bytes = field(repr=False)
    security_version: int
    created_at: datetime
    authenticated_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    selected_membership_id: uuid.UUID | None = None
    selected_membership_version: int | None = None

    def is_valid(self, *, now: datetime, security_version: int) -> bool:
        return (
            self.revoked_at is None
            and self.security_version == security_version
            and now < self.idle_expires_at
            and now < self.absolute_expires_at
        )


@dataclass(frozen=True, slots=True)
class IssuedSession:
    record: SessionRecord
    secrets: SessionSecrets = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreAuthState:
    state_digest: bytes = field(repr=False)
    csrf_digest: bytes = field(repr=False)
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IssuedPreAuth:
    state: PreAuthState
    state_token: str = field(repr=False)
    csrf_token: str = field(repr=False)


class SessionStore(Protocol):
    async def current_time(self) -> datetime: ...
    async def write_security_event(self, event: SecurityAuditEvent) -> None: ...
    async def save(self, record: SessionRecord) -> None: ...
    async def get_by_digest(self, digest: bytes) -> SessionRecord | None: ...
    async def active_for_user(self, user_id: uuid.UUID) -> list[SessionRecord]: ...
    async def replace(self, record: SessionRecord) -> None: ...
    async def save_preauth(self, state: PreAuthState) -> None: ...
    async def get_preauth(self, digest: bytes) -> PreAuthState | None: ...
    async def replace_preauth(self, state: PreAuthState) -> None: ...


class MemorySessionStore:
    """Deterministic contract store; PostgreSQL remains the production source of truth."""

    def __init__(self) -> None:
        self.sessions: dict[bytes, SessionRecord] = {}
        self.preauth: dict[bytes, PreAuthState] = {}
        self.security_events: list[SecurityAuditEvent] = []

    async def current_time(self) -> datetime:
        return datetime.now(UTC)

    async def write_security_event(self, event: SecurityAuditEvent) -> None:
        # Contract-test evidence only; production uses the PostgreSQL writer.
        self.security_events.append(event)

    async def save(self, record: SessionRecord) -> None:
        self.sessions[record.bearer_digest] = record

    async def get_by_digest(self, digest: bytes) -> SessionRecord | None:
        return self.sessions.get(digest)

    async def active_for_user(self, user_id: uuid.UUID) -> list[SessionRecord]:
        return [
            item
            for item in self.sessions.values()
            if item.user_id == user_id and item.revoked_at is None
        ]

    async def replace(self, record: SessionRecord) -> None:
        for key, value in list(self.sessions.items()):
            if value.id == record.id:
                del self.sessions[key]
        self.sessions[record.bearer_digest] = record

    async def save_preauth(self, state: PreAuthState) -> None:
        self.preauth[state.state_digest] = state

    async def get_preauth(self, digest: bytes) -> PreAuthState | None:
        return self.preauth.get(digest)

    async def replace_preauth(self, state: PreAuthState) -> None:
        self.preauth[state.state_digest] = state


class SessionService:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    async def issue(
        self, user_id: uuid.UUID, security_version: int, *, now: datetime | None = None
    ) -> IssuedSession:
        now = now or await self.store.current_time()
        active = sorted(
            (
                item
                for item in await self.store.active_for_user(user_id)
                if item.is_valid(now=now, security_version=security_version)
            ),
            key=lambda item: (item.created_at, item.id.hex),
        )
        while len(active) >= MAX_CONCURRENT_SESSIONS:
            oldest = active.pop(0)
            await self.store.replace(
                replace(oldest, revoked_at=now, revoked_reason="concurrent_limit")
            )
            await self.store.write_security_event(
                SecurityAuditEvent(
                    event_type=SecurityEventType.SESSION_REVOKED,
                    result=SecurityEventResult.SUCCESS,
                    reason_code=SecurityReasonCode.CONCURRENT_LIMIT,
                    user_id=oldest.user_id,
                    session_id=oldest.id,
                )
            )
        bearer, csrf = _token(BEARER_BYTES), _token(CSRF_BYTES)
        record = SessionRecord(
            uuid.uuid7(),
            user_id,
            token_digest(bearer),
            token_digest(csrf),
            security_version,
            now,
            now,
            now,
            now + IDLE_TIMEOUT,
            now + ABSOLUTE_TIMEOUT,
        )
        await self.store.save(record)
        return IssuedSession(record, SessionSecrets(bearer, csrf))

    async def resolve(
        self, bearer: str, security_version: int, *, now: datetime | None = None
    ) -> SessionRecord | None:
        now = now or await self.store.current_time()
        record = await self.store.get_by_digest(token_digest(bearer))
        if record is None or not record.is_valid(now=now, security_version=security_version):
            return None
        if now - record.last_seen_at >= LAST_SEEN_INTERVAL:
            record = replace(
                record,
                last_seen_at=now,
                idle_expires_at=min(now + IDLE_TIMEOUT, record.absolute_expires_at),
            )
            await self.store.replace(record)
        return record

    async def _revoke(
        self, bearer: str, event_type: SecurityEventType, *, now: datetime | None = None
    ) -> bool:
        record = await self.store.get_by_digest(token_digest(bearer))
        if record is None or record.revoked_at is not None:
            return False
        await self.store.replace(
            replace(record, revoked_at=now or datetime.now(UTC), revoked_reason="logout")
        )
        await self.store.write_security_event(
            SecurityAuditEvent(
                event_type=event_type,
                result=SecurityEventResult.SUCCESS,
                reason_code=SecurityReasonCode.LOGOUT,
                user_id=record.user_id,
                session_id=record.id,
            )
        )
        return True

    async def logout(self, bearer: str, *, now: datetime | None = None) -> bool:
        return await self._revoke(bearer, SecurityEventType.LOGOUT, now=now)

    async def revoke_current(self, bearer: str, *, now: datetime | None = None) -> bool:
        return await self._revoke(bearer, SecurityEventType.SESSION_REVOKED, now=now)

    async def revoke_all(self, user_id: uuid.UUID, *, now: datetime | None = None) -> int:
        now = now or await self.store.current_time()
        count = 0
        for record in await self.store.active_for_user(user_id):
            await self.store.replace(replace(record, revoked_at=now, revoked_reason="revoke_all"))
            count += 1
        if count:
            await self.store.write_security_event(
                SecurityAuditEvent(
                    event_type=SecurityEventType.ALL_SESSIONS_REVOKED,
                    result=SecurityEventResult.SUCCESS,
                    reason_code=SecurityReasonCode.REVOKE_ALL,
                    user_id=user_id,
                )
            )
        return count

    async def rotate_to_membership(
        self,
        bearer: str,
        security_version: int,
        membership_id: uuid.UUID,
        membership_version: int,
        *,
        now: datetime | None = None,
    ) -> IssuedSession | None:
        now = now or await self.store.current_time()
        old = await self.resolve(bearer, security_version, now=now)
        if old is None:
            return None
        new_bearer, new_csrf = _token(), _token()
        rotated = replace(
            old,
            bearer_digest=token_digest(new_bearer),
            csrf_digest=token_digest(new_csrf),
            selected_membership_id=membership_id,
            selected_membership_version=membership_version,
            last_seen_at=now,
        )
        await self.store.replace(rotated)
        return IssuedSession(rotated, SessionSecrets(new_bearer, new_csrf))

    async def rotate(
        self, bearer: str, security_version: int, *, now: datetime | None = None
    ) -> IssuedSession | None:
        now = now or await self.store.current_time()
        old = await self.resolve(bearer, security_version, now=now)
        if old is None:
            return None
        new_bearer, new_csrf = _token(), _token()
        rotated = replace(
            old,
            bearer_digest=token_digest(new_bearer),
            csrf_digest=token_digest(new_csrf),
            last_seen_at=now,
        )
        await self.store.replace(rotated)
        return IssuedSession(rotated, SessionSecrets(new_bearer, new_csrf))

    async def issue_preauth(self, *, now: datetime | None = None) -> IssuedPreAuth:
        now = now or await self.store.current_time()
        state_token, csrf = _token(), _token()
        state = PreAuthState(
            token_digest(state_token), token_digest(csrf), now, now + PREAUTH_LIFETIME
        )
        await self.store.save_preauth(state)
        return IssuedPreAuth(state, state_token, csrf)

    async def consume_preauth(
        self, state_token: str, csrf: str, *, now: datetime | None = None
    ) -> bool:
        now = now or await self.store.current_time()
        state = await self.store.get_preauth(token_digest(state_token))
        if state is None or state.consumed_at is not None or now >= state.expires_at:
            return False
        if not token_matches(csrf, state.csrf_digest):
            return False
        await self.store.replace_preauth(replace(state, consumed_at=now))
        return True
