"""Authentication operation events use the caller's PostgreSQL transaction."""

from __future__ import annotations

import uuid

import pytest

from app.audit.contracts import SecurityEventType, SecurityReasonCode
from app.auth.sessions import MAX_CONCURRENT_SESSIONS, MemorySessionStore, SessionService


@pytest.mark.parametrize(
    ("operation", "event_type"),
    [("logout", SecurityEventType.LOGOUT), ("revoke_current", SecurityEventType.SESSION_REVOKED)],
)
async def test_single_session_revocation_records_exactly_once(
    operation: str, event_type: SecurityEventType
) -> None:
    store = MemorySessionStore()
    service = SessionService(store)
    issued = await service.issue(uuid.uuid7(), 1)
    revoke = getattr(service, operation)
    assert await revoke(issued.secrets.bearer)
    assert not await revoke(issued.secrets.bearer)
    assert len(store.security_events) == 1
    event = store.security_events[0]
    assert (event.event_type, event.user_id, event.session_id) == (
        event_type,
        issued.record.user_id,
        issued.record.id,
    )


async def test_revoke_all_has_one_aggregate_event_only_after_a_mutation() -> None:
    store = MemorySessionStore()
    service = SessionService(store)
    user = uuid.uuid7()
    await service.issue(user, 1)
    await service.issue(user, 1)
    assert await service.revoke_all(user) == 2
    assert await service.revoke_all(user) == 0
    assert [event.event_type for event in store.security_events] == [
        SecurityEventType.ALL_SESSIONS_REVOKED
    ]


async def test_concurrent_limit_revocation_records_the_old_session_without_fake_login() -> None:
    store = MemorySessionStore()
    service = SessionService(store)
    user = uuid.uuid7()
    oldest = await service.issue(user, 1)
    for _ in range(MAX_CONCURRENT_SESSIONS):
        await service.issue(user, 1)
    assert len(store.security_events) == 1
    event = store.security_events[0]
    assert event.event_type is SecurityEventType.SESSION_REVOKED
    assert event.reason_code is SecurityReasonCode.CONCURRENT_LIMIT
    assert event.session_id == oldest.record.id
