"""Transaction-bound security event writer; no raw request data or transaction ownership."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.audit.contracts import (
    ROLE_EVENT_TYPES,
    InvalidSecurityAuditEventError,
    SecurityAuditEvent,
    SecurityEventType,
)
from app.core.context import get_internal_correlation_id
from app.db.tenant_transaction import TenantTransaction


class SecurityAuditWriteError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Security audit write failed.")


class SecurityEventWriter:
    """Append a validated intent on the caller's already-open transaction.

    The database verifies identity links independently. Role events require an
    armed intent attested by actual RBAC row mutations under existing FORCE RLS.
    Retention events are available only through the separate maintenance capability.
    """

    def __init__(self, connection: AsyncConnection | TenantTransaction) -> None:
        self._connection = connection
        self._correlation_id = get_internal_correlation_id() or uuid.uuid7()
        self._role_intent: tuple[SecurityAuditEvent, uuid.UUID] | None = None

    def __repr__(self) -> str:
        return "<SecurityEventWriter>"

    async def write(self, event: SecurityAuditEvent) -> None:
        if type(event) is not SecurityAuditEvent:
            raise InvalidSecurityAuditEventError()
        event._validate()
        if event.event_type is SecurityEventType.SECURITY_EVENTS_PRUNED:
            raise SecurityAuditWriteError()
        if event.event_type in ROLE_EVENT_TYPES and (
            self._role_intent is None or self._role_intent[0] != event
        ):
            raise SecurityAuditWriteError()
        self._require_transaction()
        try:
            await self._connection.execute(
                text(
                    """SELECT auth.append_security_event(
                    CAST(:id AS uuid), CAST(:type AS text), CAST(:result AS text),
                    CAST(:reason AS text), CAST(:user AS uuid), CAST(:session AS uuid),
                    CAST(:membership AS uuid), CAST(:subject AS bytea),
                    CAST(:correlation AS uuid), CAST(:role AS uuid),
                    CAST(:target_membership AS uuid), CAST(:permission AS text),
                    CAST(:subject_kind AS text), CAST(:subject_key_id AS smallint),
                    CAST(:affected_count AS bigint))"""
                ),
                {
                    "id": self._role_intent[1]
                    if event.event_type in ROLE_EVENT_TYPES and self._role_intent
                    else uuid.uuid7(),
                    "type": event.event_type.value,
                    "result": event.result.value,
                    "reason": event.reason_code.value if event.reason_code is not None else None,
                    "user": event.user_id,
                    "session": event.session_id,
                    "membership": event.membership_id,
                    "subject": event.subject_digest,
                    "correlation": self._correlation_id,
                    "role": event.role_id,
                    "target_membership": event.target_membership_id,
                    "permission": str(event.permission_id)
                    if event.permission_id is not None
                    else None,
                    "subject_kind": event.subject_kind.value
                    if event.subject_kind is not None
                    else None,
                    "subject_key_id": event.subject_key_id,
                    "affected_count": event.affected_count,
                },
            )
            if event.event_type in ROLE_EVENT_TYPES:
                self._role_intent = None
        except SQLAlchemyError:
            # No driver text, SQL, bind parameters or exception chain crosses
            # this boundary. The caller's transaction context performs rollback.
            raise SecurityAuditWriteError() from None

    def _require_transaction(self) -> None:
        # TenantTransaction exposes data operations only and cannot autobegin;
        # its session rejects work outside the existing tenant_transaction scope.
        if (
            not isinstance(self._connection, TenantTransaction)
            and not self._connection.in_transaction()
        ):
            raise SecurityAuditWriteError()

    async def prepare_role(self, event: SecurityAuditEvent, membership_version: int) -> None:
        if type(event) is not SecurityAuditEvent:
            raise InvalidSecurityAuditEventError()
        event._validate()
        if event.event_type not in ROLE_EVENT_TYPES or self._role_intent is not None:
            raise SecurityAuditWriteError()
        self._require_transaction()
        event_id = uuid.uuid7()
        try:
            await self._connection.execute(
                text("""SELECT auth.prepare_role_security_event(
                    CAST(:id AS uuid),CAST(:type AS text),CAST(:user AS uuid),
                    CAST(:session AS uuid),CAST(:membership AS uuid),CAST(:role AS uuid),
                    CAST(:target AS uuid),CAST(:permission AS text),CAST(:correlation AS uuid),
                    CAST(:version AS integer))"""),
                {
                    "id": event_id,
                    "type": event.event_type.value,
                    "user": event.user_id,
                    "session": event.session_id,
                    "membership": event.membership_id,
                    "role": event.role_id,
                    "target": event.target_membership_id,
                    "permission": str(event.permission_id) if event.permission_id else None,
                    "correlation": self._correlation_id,
                    "version": membership_version,
                },
            )
            self._role_intent = (event, event_id)
        except SQLAlchemyError:
            raise SecurityAuditWriteError() from None

    async def cancel_role(self, event: SecurityAuditEvent) -> None:
        """Cancel only a no-op; PostgreSQL rejects cancelling an attested mutation."""
        if self._role_intent is None or self._role_intent[0] != event:
            raise SecurityAuditWriteError()
        self._require_transaction()
        try:
            await self._connection.execute(
                text("SELECT auth.cancel_role_security_event(CAST(:id AS uuid))"),
                {"id": self._role_intent[1]},
            )
            self._role_intent = None
        except SQLAlchemyError:
            raise SecurityAuditWriteError() from None
