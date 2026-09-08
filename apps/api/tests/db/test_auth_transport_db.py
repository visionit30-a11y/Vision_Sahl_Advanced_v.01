"""Real PostgreSQL proofs for the production session transport."""

from __future__ import annotations

import asyncio
import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.audit import request_events
from app.auth.controls import SecurityEventWriter, ThrottleScope, sensitive_key_digest
from app.auth.http import CsrfRejectedError, TenantContextChangedError
from app.auth.postgres import PostgresSessionStore
from app.auth.sessions import IssuedSession, SessionService, token_digest
from app.auth.tenants import (
    PostgresMembershipAuthority,
    SessionRejectedError,
    TenantAccessDeniedError,
    TrustedTenantService,
)
from app.core.config import AuthHmacKeyMissingError, Settings
from app.db import auth_http
from app.db.auth_http import AuthHttpService

LOCAL_ORIGIN = "http://localhost:5187"


@dataclass
class TransportFixture:
    service: AuthHttpService
    migrator: Engine
    settings: Settings
    user: uuid.UUID
    tenants: tuple[uuid.UUID, uuid.UUID]
    memberships: tuple[uuid.UUID, uuid.UUID]
    issued: IssuedSession = field(repr=False)
    email: str
    client_ip: str

    def request(self, csrf: str, membership: uuid.UUID, method: str = "POST") -> Request:
        return Request(
            {
                "type": "http",
                "method": method,
                "path": "/auth/tenant/switch",
                "headers": [
                    (b"origin", LOCAL_ORIGIN.encode()),
                    (b"x-csrf-token", csrf.encode()),
                    (b"x-expected-membership-id", str(membership).encode()),
                ],
                "scheme": "http",
                "server": ("localhost", 5187),
                "client": (self.client_ip, 1234),
                "query_string": b"",
            }
        )


@pytest.fixture
async def transport_fixture(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[TransportFixture]:
    config = Settings(
        app_env="test", auth_local_http_origin=LOCAL_ORIGIN, auth_hmac_key=secrets.token_hex(32)
    )
    migrator = create_engine(settings.required_migration_database_url, poolclass=NullPool)
    runtime = create_async_engine(settings.database_url, poolclass=NullPool)
    monkeypatch.setattr(auth_http, "_engine", runtime)
    monkeypatch.setattr(auth_http, "get_settings", lambda: config)
    monkeypatch.setattr(request_events, "get_settings", lambda: config)
    user = uuid.uuid7()
    tenants = (uuid.uuid7(), uuid.uuid7())
    memberships = (uuid.uuid7(), uuid.uuid7())
    email = f"transport-{user.hex}@example.test"
    client_ip = f"test-{user.hex}"
    with migrator.begin() as db:
        db.execute(
            text(
                "INSERT INTO auth.users(id,email,normalized_email,status) "
                "VALUES (:id,:email,:email,'active')"
            ),
            {"id": user, "email": email},
        )
        for number, (tenant, membership) in enumerate(zip(tenants, memberships, strict=True)):
            db.execute(
                text(
                    "INSERT INTO public.tenants(id,slug,name_ar,name_en,status) "
                    "VALUES (:id,:slug,:name,:name,'active')"
                ),
                {"id": tenant, "slug": f"transport-{tenant.hex}", "name": f"Tenant {number}"},
            )
            db.execute(
                text(
                    "INSERT INTO auth.tenant_memberships"
                    "(id,user_id,tenant_id,status,joined_at) "
                    "VALUES (:id,:user,:tenant,'active',:now)"
                ),
                {"id": membership, "user": user, "tenant": tenant, "now": datetime.now(UTC)},
            )
    try:
        async with runtime.begin() as db:
            sessions = SessionService(PostgresSessionStore(db))
            issued = await sessions.issue(user, 1)
            switched = await TrustedTenantService(sessions, PostgresMembershipAuthority(db)).switch(
                issued.secrets.bearer, memberships[0]
            )
        yield TransportFixture(
            AuthHttpService(),
            migrator,
            config,
            user,
            tenants,
            memberships,
            switched.issued_session,
            email,
            client_ip,
        )
    finally:
        await runtime.dispose()
        with migrator.begin() as db:
            db.execute(text("DELETE FROM auth.security_events WHERE user_id=:user"), {"user": user})
            db.execute(
                text("DELETE FROM auth.throttle_buckets WHERE key_digest=:digest"),
                {
                    "digest": sensitive_key_digest(
                        config.required_auth_hmac_key, ThrottleScope.CSRF_IP, client_ip
                    )
                },
            )
            db.execute(text("DELETE FROM auth.sessions WHERE user_id=:user"), {"user": user})
            db.execute(
                text("DELETE FROM auth.tenant_memberships WHERE user_id=:user"), {"user": user}
            )
            db.execute(text("DELETE FROM auth.users WHERE id=:user"), {"user": user})
            for tenant in tenants:
                db.execute(text("DELETE FROM public.tenants WHERE id=:tenant"), {"tenant": tenant})
        migrator.dispose()


async def test_production_identity_and_membership_reads_use_live_db(
    transport_fixture: TransportFixture,
) -> None:
    data = transport_fixture
    identity = await data.service.me(data.issued.secrets.bearer)
    assert identity.id == data.user and identity.email == data.email
    assert identity.selected_membership_id == data.memberships[0]
    memberships = await data.service.memberships(data.issued.secrets.bearer)
    assert {item.id for item in memberships} == set(data.memberships)
    assert {item.tenant_id for item in memberships} == set(data.tenants)


async def test_bootstrap_is_stable_and_persists_only_digest(
    transport_fixture: TransportFixture,
) -> None:
    data = transport_fixture
    request = data.request(data.issued.secrets.csrf_token, data.memberships[0], "GET")
    first = await data.service.bootstrap_csrf(data.issued.secrets.bearer, request)
    second = await data.service.bootstrap_csrf(data.issued.secrets.bearer, request)
    assert first == second and first != data.issued.secrets.bearer
    with data.migrator.connect() as db:
        stored = db.execute(
            text("SELECT csrf_digest,bearer_digest FROM auth.sessions WHERE id=:id"),
            {"id": data.issued.record.id},
        ).one()
        assert bytes(stored.csrf_digest) == token_digest(first)
        assert bytes(stored.bearer_digest) == token_digest(data.issued.secrets.bearer)
        assert first.encode() not in bytes(stored.csrf_digest)


@pytest.mark.parametrize("operation", ["me", "memberships", "bootstrap"])
async def test_inactive_user_is_rejected_on_each_identity_path(
    transport_fixture: TransportFixture, operation: str
) -> None:
    data = transport_fixture
    with data.migrator.begin() as db:
        db.execute(text("UPDATE auth.users SET status='suspended' WHERE id=:id"), {"id": data.user})
    with pytest.raises(SessionRejectedError):
        if operation == "bootstrap":
            await data.service.bootstrap_csrf(
                data.issued.secrets.bearer,
                data.request(data.issued.secrets.csrf_token, data.memberships[0], "GET"),
            )
        else:
            await getattr(data.service, operation)(data.issued.secrets.bearer)


async def test_tenant_switch_rotates_bearer_csrf_and_records_trusted_event(
    transport_fixture: TransportFixture,
) -> None:
    data = transport_fixture
    old = data.issued
    rotated = await data.service.switch(
        old.secrets.bearer,
        data.memberships[1],
        data.request(old.secrets.csrf_token, data.memberships[0]),
    )
    assert rotated.secrets.bearer != old.secrets.bearer
    assert rotated.secrets.csrf_token != old.secrets.csrf_token
    assert (
        await data.service.me(rotated.secrets.bearer)
    ).selected_membership_id == data.memberships[1]
    with pytest.raises(SessionRejectedError):
        await data.service.me(old.secrets.bearer)
    with pytest.raises(CsrfRejectedError):
        await data.service.logout(
            rotated.secrets.bearer, data.request(old.secrets.csrf_token, data.memberships[1])
        )
    with pytest.raises(TenantContextChangedError):
        await data.service.logout(
            rotated.secrets.bearer, data.request(rotated.secrets.csrf_token, data.memberships[0])
        )
    with data.migrator.connect() as db:
        events = db.execute(
            text(
                "SELECT event_type,membership_id FROM auth.security_events "
                "WHERE user_id=:user ORDER BY id"
            ),
            {"user": data.user},
        ).all()
        assert [tuple(event) for event in events] == [
            ("tenant_switch", data.memberships[1]),
            ("csrf_rejected", None),
            ("membership_denied", None),
        ]


async def test_forged_membership_is_denied_without_recording_selector_as_proof(
    transport_fixture: TransportFixture,
) -> None:
    data = transport_fixture
    forged = uuid.uuid7()
    with pytest.raises(TenantAccessDeniedError):
        await data.service.switch(
            data.issued.secrets.bearer,
            forged,
            data.request(data.issued.secrets.csrf_token, data.memberships[0]),
        )
    with data.migrator.connect() as db:
        event = db.execute(
            text("SELECT event_type,membership_id FROM auth.security_events WHERE user_id=:user"),
            {"user": data.user},
        ).one()
        assert tuple(event) == ("membership_denied", None)
    assert (await data.service.me(data.issued.secrets.bearer)).id == data.user


async def test_logout_revokes_real_session_and_writes_event(
    transport_fixture: TransportFixture,
) -> None:
    data = transport_fixture
    await data.service.logout(
        data.issued.secrets.bearer,
        data.request(data.issued.secrets.csrf_token, data.memberships[0]),
    )
    with pytest.raises(SessionRejectedError):
        await data.service.me(data.issued.secrets.bearer)
    with data.migrator.connect() as db:
        assert (
            db.scalar(
                text(
                    "SELECT count(*) FROM auth.security_events "
                    "WHERE user_id=:user AND event_type='logout'"
                ),
                {"user": data.user},
            )
            == 1
        )


@pytest.mark.parametrize("operation", ["switch", "logout"])
async def test_required_event_failure_rolls_back_session_mutation(
    transport_fixture: TransportFixture, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    data = transport_fixture

    async def fail_event(self: SecurityEventWriter, *args: object, **kwargs: object) -> None:
        raise RuntimeError("event unavailable")

    monkeypatch.setattr(SecurityEventWriter, "write", fail_event)
    request = data.request(data.issued.secrets.csrf_token, data.memberships[0])
    with pytest.raises(RuntimeError, match="event unavailable"):
        if operation == "switch":
            await data.service.switch(data.issued.secrets.bearer, data.memberships[1], request)
        else:
            await data.service.logout(data.issued.secrets.bearer, request)
    identity = await data.service.me(data.issued.secrets.bearer)
    assert identity.selected_membership_id == data.memberships[0]


async def test_bootstrap_missing_hmac_key_fails_closed(
    transport_fixture: TransportFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = transport_fixture
    missing = data.settings.model_copy(update={"auth_hmac_key": None})
    monkeypatch.setattr(auth_http, "get_settings", lambda: missing)
    with pytest.raises(AuthHmacKeyMissingError):
        await data.service.bootstrap_csrf(
            data.issued.secrets.bearer,
            data.request(data.issued.secrets.csrf_token, data.memberships[0], "GET"),
        )


async def test_bootstrap_racing_switch_cannot_restore_old_csrf_or_bearer(
    transport_fixture: TransportFixture,
) -> None:
    data = transport_fixture
    old_bearer = data.issued.secrets.bearer
    bootstrap_request = data.request(data.issued.secrets.csrf_token, data.memberships[0], "GET")
    csrf = await data.service.bootstrap_csrf(old_bearer, bootstrap_request)
    bootstrap, switched = await asyncio.gather(
        data.service.bootstrap_csrf(old_bearer, bootstrap_request),
        data.service.switch(
            old_bearer, data.memberships[1], data.request(csrf, data.memberships[0])
        ),
        return_exceptions=True,
    )
    assert isinstance(switched, IssuedSession)
    assert bootstrap == csrf or isinstance(bootstrap, SessionRejectedError)
    replacement_csrf = await data.service.bootstrap_csrf(
        switched.secrets.bearer,
        data.request(switched.secrets.csrf_token, data.memberships[1], "GET"),
    )
    assert replacement_csrf == switched.secrets.csrf_token
    assert replacement_csrf != csrf
    with pytest.raises(SessionRejectedError):
        await data.service.me(old_bearer)
