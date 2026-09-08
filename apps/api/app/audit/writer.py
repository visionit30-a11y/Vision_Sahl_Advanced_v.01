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


class SecurityAuditWriteError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Security audit write failed.")


class SecurityEventWriter:
    """Append a validated intent on the caller's already-open transaction.

    The database verifies identity links independently. Role events are reserved
    until a proof path compatible with the existing FORCE RLS policy is approved.
    Retention events are reserved for the future maintenance capability.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection
        self._correlation_id = uuid.uuid7()

    def __repr__(self) -> str:
        return "<SecurityEventWriter>"

    async def write(self, event: SecurityAuditEvent) -> None:
        if type(event) is not SecurityAuditEvent:
            raise InvalidSecurityAuditEventError()
        event._validate()
        if event.event_type in ROLE_EVENT_TYPES or (
            event.event_type is SecurityEventType.SECURITY_EVENTS_PRUNED
        ):
            raise SecurityAuditWriteError()
        if not self._connection.in_transaction():
            raise SecurityAuditWriteError()
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
                    "id": uuid.uuid7(),
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
        except SQLAlchemyError:
            # No driver text, SQL, bind parameters or exception chain crosses
            # this boundary. The caller's transaction context performs rollback.
            raise SecurityAuditWriteError() from None
