"""Durable denial events after the rejected request transaction has rolled back."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.audit.contracts import (
    SecurityAuditEvent,
    SecurityEventResult,
    SecurityEventType,
    SecurityReasonCode,
)
from app.audit.writer import SecurityAuditWriteError, SecurityEventWriter
from app.auth.http import CSRF_HEADER, CsrfRejectedError, TenantContextChangedError, validate_origin
from app.auth.sessions import SessionRecord
from app.auth.tenants import AuthenticatedPrincipal, TenantAccessDeniedError
from app.authorization.permissions import PermissionId
from app.core.config import get_settings
from app.core.logging import get_logger


@dataclass(slots=True)
class RequestAuditIdentity:
    # Set only from the server's validated session, never a request selector.
    session: SessionRecord | None = None


def _denial(
    error: Exception,
    request: Request | None,
    identity: RequestAuditIdentity,
    *,
    origin_failure: bool = False,
) -> SecurityAuditEvent:
    kind = SecurityEventType.MEMBERSHIP_DENIED
    reason = SecurityReasonCode.MEMBERSHIP_UNAVAILABLE
    if origin_failure:
        kind = SecurityEventType.ORIGIN_REJECTED
        reason = SecurityReasonCode.ORIGIN_DENIED
    elif isinstance(error, CsrfRejectedError):
        kind = SecurityEventType.CSRF_REJECTED
        reason = SecurityReasonCode.CSRF_INVALID
        if request is not None:
            settings = get_settings()
            try:
                validate_origin(
                    request,
                    set(settings.auth_origin_list),
                    local_http_origin=settings.auth_local_http_origin,
                )
            except CsrfRejectedError:
                kind = SecurityEventType.ORIGIN_REJECTED
                reason = SecurityReasonCode.ORIGIN_DENIED
            else:
                if not request.headers.get(CSRF_HEADER):
                    reason = SecurityReasonCode.CSRF_MISSING
    record = identity.session
    return SecurityAuditEvent(
        event_type=kind,
        result=SecurityEventResult.DENIED,
        reason_code=reason,
        user_id=record.user_id if record else None,
        session_id=record.id if record else None,
    )


@asynccontextmanager
async def audited_auth_transaction(
    engine: AsyncEngine, request: Request | None = None
) -> AsyncIterator[tuple[AsyncConnection, RequestAuditIdentity]]:
    """Success events stay in caller transaction; rejected work is rolled back first."""
    identity = RequestAuditIdentity()
    try:
        async with engine.begin() as connection:
            yield connection, identity
    except (TenantAccessDeniedError, CsrfRejectedError, TenantContextChangedError) as error:
        try:
            async with engine.begin() as connection:
                await SecurityEventWriter(connection).write(_denial(error, request, identity))
        except SQLAlchemyError, SecurityAuditWriteError:
            # Never turn a denial into success, or claim a durable event was written.
            get_logger(__name__).error("audit_write_failed")
        raise


class SecurityDenialAuditor:
    """Persist a rejected authorization decision; never participates in ALLOW."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def authorization_denied(
        self, principal: AuthenticatedPrincipal | None, permission_id: PermissionId
    ) -> None:
        event = SecurityAuditEvent(
            event_type=SecurityEventType.AUTHORIZATION_DENIED,
            result=SecurityEventResult.DENIED,
            reason_code=SecurityReasonCode.PERMISSION_DENIED,
            user_id=principal.user_id if principal else None,
            session_id=principal.session_id if principal else None,
            membership_id=principal.membership_id if principal else None,
            permission_id=permission_id,
        )
        try:
            async with self._engine.begin() as connection:
                await SecurityEventWriter(connection).write(event)
        except SQLAlchemyError, SecurityAuditWriteError:
            get_logger(__name__).error("audit_write_failed")

    async def request_denied(
        self,
        error: Exception,
        request: Request,
        session: SessionRecord | None = None,
        *,
        origin_failure: bool = False,
    ) -> None:
        try:
            async with self._engine.begin() as connection:
                await SecurityEventWriter(connection).write(
                    _denial(
                        error, request, RequestAuditIdentity(session), origin_failure=origin_failure
                    )
                )
        except SQLAlchemyError, SecurityAuditWriteError:
            get_logger(__name__).error("audit_write_failed")
