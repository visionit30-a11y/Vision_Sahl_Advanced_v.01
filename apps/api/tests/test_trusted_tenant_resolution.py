"""Trusted membership resolution and tenant-switching service tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from app.auth.sessions import IssuedSession, MemorySessionStore, SessionService, token_matches
from app.auth.tenants import (
    MembershipProof,
    SessionRejectedError,
    TenantAccessDeniedError,
    TrustedTenantService,
)


@dataclass
class Entry:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    version: int = 1
    user_active: bool = True
    membership_status: str = "active"
    tenant_active: bool = True
    security_version: int = 1


class MemoryAuthority:
    def __init__(self) -> None:
        self.entries: dict[uuid.UUID, Entry] = {}

    async def resolve_active(
        self,
        *,
        user_id: uuid.UUID,
        membership_id: uuid.UUID,
        membership_version: int | None,
        security_version: int,
    ) -> MembershipProof | None:
        entry = self.entries.get(membership_id)
        if entry is None or entry.user_id != user_id or not entry.user_active:
            return None
        if entry.membership_status != "active" or not entry.tenant_active:
            return None
        if entry.security_version != security_version:
            return None
        if membership_version is not None and entry.version != membership_version:
            return None
        return MembershipProof(entry.tenant_id, membership_id, entry.version)


async def setup_access() -> tuple[
    TrustedTenantService, MemoryAuthority, IssuedSession, uuid.UUID, Entry
]:
    user_id, membership_id = uuid.uuid7(), uuid.uuid7()
    authority = MemoryAuthority()
    entry = Entry(user_id, uuid.uuid7())
    authority.entries[membership_id] = entry
    sessions = SessionService(MemorySessionStore())
    issued = await sessions.issue(user_id, 1)
    return TrustedTenantService(sessions, authority), authority, issued, membership_id, entry


async def test_valid_session_and_membership_create_principal_then_context() -> None:
    service, _, issued, membership_id, entry = await setup_access()
    switched = await service.switch(issued.secrets.bearer, membership_id)
    access = await service.resolve(switched.issued_session.secrets.bearer)
    assert access.principal.user_id == entry.user_id
    assert access.principal.membership_id == membership_id
    assert access.context.tenant_id == entry.tenant_id


@pytest.mark.parametrize(
    "change", ["foreign", "suspended", "left", "tenant_inactive", "user_inactive", "stale"]
)
async def test_untrusted_membership_states_are_rejected(change: str) -> None:
    service, _, issued, membership_id, entry = await setup_access()
    switched = await service.switch(issued.secrets.bearer, membership_id)
    if change == "foreign":
        entry.user_id = uuid.uuid7()
    elif change in {"suspended", "left"}:
        entry.membership_status = change
    elif change == "tenant_inactive":
        entry.tenant_active = False
    elif change == "user_inactive":
        entry.user_active = False
    else:
        entry.version += 1
    with pytest.raises(TenantAccessDeniedError):
        await service.resolve(switched.issued_session.secrets.bearer)


async def test_forged_or_foreign_switch_is_rejected_without_fallback() -> None:
    service, authority, issued, _, _ = await setup_access()
    with pytest.raises(TenantAccessDeniedError):
        await service.switch(issued.secrets.bearer, uuid.uuid7())
    foreign = uuid.uuid7()
    authority.entries[foreign] = Entry(uuid.uuid7(), uuid.uuid7())
    with pytest.raises(TenantAccessDeniedError):
        await service.switch(issued.secrets.bearer, foreign)


async def test_switch_to_suspended_tenant_is_rejected() -> None:
    service, _, issued, membership_id, entry = await setup_access()
    entry.tenant_active = False
    with pytest.raises(TenantAccessDeniedError):
        await service.switch(issued.secrets.bearer, membership_id)


async def test_successful_switch_rotates_bearer_and_csrf_immediately() -> None:
    service, _, issued, membership_id, _ = await setup_access()
    switched = await service.switch(issued.secrets.bearer, membership_id)
    replacement = switched.issued_session
    with pytest.raises(SessionRejectedError):
        await service.resolve(issued.secrets.bearer)
    assert not token_matches(issued.secrets.csrf_token, replacement.record.csrf_digest)
    assert await service.resolve(replacement.secrets.bearer) == switched.access
