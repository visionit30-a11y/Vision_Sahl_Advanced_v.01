"""Production session HTTP composition over the existing PostgreSQL auth boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass, replace

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.audit.contracts import (
    SecurityAuditEvent,
    SecurityEventResult,
    SecurityEventType,
    SecurityReasonCode,
)
from app.auth.controls import (
    PostgresThrottleStore,
    SecurityEventWriter,
    ThrottleScope,
    ThrottleService,
)
from app.auth.http import (
    require_session_bearer,
    validate_expected_membership,
    validate_session_csrf,
)
from app.auth.postgres import PostgresSessionStore
from app.auth.sessions import IssuedSession, SessionRecord, SessionService, token_digest
from app.auth.tenants import (
    PostgresMembershipAuthority,
    SessionRejectedError,
    TenantAccessDeniedError,
    TrustedTenantService,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import _engine


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    id: uuid.UUID
    email: str
    selected_membership_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class SessionMembership:
    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str


def _bootstrap_token(bearer: str) -> str:
    """Derive an unrecoverable, stable synchronizer token without persisting secrets."""
    digest = hmac.new(bearer.encode("ascii"), b"sahl-csrf-bootstrap-v1", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def _active_session(
    connection: AsyncConnection, bearer: str
) -> tuple[SessionService, SessionRecord, SessionIdentity]:
    require_session_bearer(bearer)
    store = PostgresSessionStore(connection)
    record = await store.get_by_digest(token_digest(bearer))
    if record is None:
        raise SessionRejectedError()
    identity = (
        await connection.execute(
            text("SELECT * FROM auth.session_identity(:digest)"),
            {"digest": token_digest(bearer)},
        )
    ).one_or_none()
    if identity is None or record.user_id != identity.user_id:
        raise SessionRejectedError()
    now = await store.current_time()
    if not record.is_valid(now=now, security_version=identity.security_version):
        raise SessionRejectedError()
    return (
        SessionService(store),
        record,
        SessionIdentity(identity.user_id, identity.email, record.selected_membership_id),
    )


def _validate_unsafe(request: Request, record: SessionRecord) -> None:
    settings = get_settings()
    validate_expected_membership(request, record.selected_membership_id)
    validate_session_csrf(
        request,
        record,
        set(settings.auth_origin_list),
        local_http_origin=settings.auth_local_http_origin,
    )


class AuthThrottledError(AppError):
    code = "throttled"
    status_code = 429
    message = "The request could not be completed. Try again later."


class AuthHttpService:
    """Own database transactions; expose identity projections and opaque session operations."""

    async def me(self, bearer: str) -> SessionIdentity:
        async with _engine.begin() as connection:
            sessions, record, identity = await _active_session(connection, bearer)
            if record.selected_membership_id is not None:
                await TrustedTenantService(
                    sessions, PostgresMembershipAuthority(connection)
                ).resolve(bearer)
            await sessions.resolve(bearer, record.security_version)
            return identity

    async def memberships(self, bearer: str) -> list[SessionMembership]:
        async with _engine.begin() as connection:
            await _active_session(connection, bearer)
            rows = (
                await connection.execute(
                    text("SELECT * FROM auth.session_memberships(:digest)"),
                    {"digest": token_digest(bearer)},
                )
            ).all()
            return [
                SessionMembership(row.membership_id, row.tenant_id, row.tenant_name) for row in rows
            ]

    async def bootstrap_csrf(self, bearer: str, request: Request) -> str:
        require_session_bearer(bearer)
        settings = get_settings()
        # A separate transaction preserves the quota even if authentication later fails.
        async with _engine.begin() as connection:
            decision = await ThrottleService(
                PostgresThrottleStore(connection),
                settings.required_auth_hmac_key,
                key_id=settings.auth_hmac_key_id,
            ).consume(ThrottleScope.CSRF_IP, request.client.host if request.client else "unknown")
            if not decision.allowed:
                await SecurityEventWriter(connection).write(
                    SecurityAuditEvent(
                        event_type=SecurityEventType.THROTTLING_TRIGGERED,
                        result=SecurityEventResult.DENIED,
                        reason_code=SecurityReasonCode.CSRF_BOOTSTRAP,
                    )
                )
        if not decision.allowed:
            raise AuthThrottledError()
        async with _engine.begin() as connection:
            sessions, record, _ = await _active_session(connection, bearer)
            token = _bootstrap_token(bearer)
            digest = token_digest(token)
            if record.csrf_digest != digest:
                await sessions.store.replace(replace(record, csrf_digest=digest))
            return token

    async def switch(
        self, bearer: str, membership_selector: uuid.UUID, request: Request
    ) -> IssuedSession:
        denied = False
        async with _engine.begin() as connection:
            sessions, record, _ = await _active_session(connection, bearer)
            _validate_unsafe(request, record)
            writer = SecurityEventWriter(connection)
            trusted = TrustedTenantService(sessions, PostgresMembershipAuthority(connection))
            try:
                switched = await trusted.switch(bearer, membership_selector)
            except TenantAccessDeniedError:
                denied = True
                await writer.write(
                    SecurityAuditEvent(
                        event_type=SecurityEventType.MEMBERSHIP_DENIED,
                        result=SecurityEventResult.DENIED,
                        user_id=record.user_id,
                        session_id=record.id,
                        reason_code=SecurityReasonCode.MEMBERSHIP_UNAVAILABLE,
                    )
                )
            else:
                issued = switched.issued_session
                # Bootstrap and tenant rotation share one stable per-bearer token contract.
                csrf = _bootstrap_token(issued.secrets.bearer)
                issued = replace(
                    issued,
                    record=replace(issued.record, csrf_digest=token_digest(csrf)),
                    secrets=replace(issued.secrets, csrf_token=csrf),
                )
                await sessions.store.replace(issued.record)
                await writer.write(
                    SecurityAuditEvent(
                        event_type=SecurityEventType.TENANT_SWITCH,
                        result=SecurityEventResult.SUCCESS,
                        user_id=issued.record.user_id,
                        session_id=issued.record.id,
                        membership_id=switched.access.principal.membership_id,
                    )
                )
        if denied:
            raise TenantAccessDeniedError()
        return issued

    async def logout(self, bearer: str, request: Request) -> None:
        async with _engine.begin() as connection:
            sessions, record, _ = await _active_session(connection, bearer)
            _validate_unsafe(request, record)
            if not await sessions.logout(bearer, now=await sessions.store.current_time()):
                raise SessionRejectedError()
            await SecurityEventWriter(connection).write(
                SecurityAuditEvent(
                    event_type=SecurityEventType.LOGOUT,
                    result=SecurityEventResult.SUCCESS,
                    user_id=record.user_id,
                    session_id=record.id,
                )
            )


auth_http_service = AuthHttpService()
