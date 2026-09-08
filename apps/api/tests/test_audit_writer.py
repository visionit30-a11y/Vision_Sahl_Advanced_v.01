"""Writer-only proofs; live PostgreSQL enforcement requires the approved migration."""

from __future__ import annotations

import traceback
import uuid
from typing import cast

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.audit.contracts import (
    InvalidSecurityAuditEventError,
    SecurityAuditEvent,
    SecurityEventResult,
    SecurityEventType,
)
from app.audit.writer import SecurityAuditWriteError, SecurityEventWriter


class _Connection:
    def __init__(self, *, active: bool = True, failure: DBAPIError | None = None) -> None:
        self.active = active
        self.failure = failure
        self.writes: list[dict[str, object]] = []

    def in_transaction(self) -> bool:
        return self.active

    async def execute(self, statement: object, parameters: dict[str, object]) -> None:
        self.writes.append(parameters)
        if self.failure is not None:
            raise self.failure


def _writer(connection: _Connection) -> SecurityEventWriter:
    return SecurityEventWriter(cast(AsyncConnection, connection))


def _failure_event() -> SecurityAuditEvent:
    return SecurityAuditEvent(
        event_type=SecurityEventType.LOGIN_FAILURE,
        result=SecurityEventResult.FAILURE,
    )


async def test_writer_requires_callers_open_transaction() -> None:
    connection = _Connection(active=False)
    with pytest.raises(SecurityAuditWriteError, match=r"^Security audit write failed\.$"):
        await _writer(connection).write(_failure_event())
    assert connection.writes == []


async def test_writer_creates_internal_ids_without_committing() -> None:
    connection = _Connection()
    writer = _writer(connection)
    await writer.write(_failure_event())
    await writer.write(_failure_event())
    first, second = connection.writes
    assert isinstance(first["id"], uuid.UUID) and first["id"].version == 7
    assert isinstance(first["correlation"], uuid.UUID) and first["correlation"].version == 7
    assert first["id"] != second["id"]
    assert first["correlation"] == second["correlation"]
    assert first["type"] == "login_failure" and first["result"] == "failure"
    assert first["user"] is None and first["session"] is None
    # The connection deliberately provides no begin/commit/rollback methods.
    assert repr(writer) == "<SecurityEventWriter>"


async def test_separate_writers_do_not_reuse_correlation() -> None:
    connection = _Connection()
    await _writer(connection).write(_failure_event())
    await _writer(connection).write(_failure_event())
    assert connection.writes[0]["correlation"] != connection.writes[1]["correlation"]


async def test_writer_rejects_raw_input_before_database() -> None:
    connection = _Connection()
    canary = uuid.uuid4().hex
    with pytest.raises(InvalidSecurityAuditEventError) as caught:
        await _writer(connection).write(cast(SecurityAuditEvent, canary))
    assert canary not in str(caught.value) + repr(caught.value)
    assert connection.writes == []


async def test_writer_revalidates_tampered_intent() -> None:
    connection = _Connection()
    event = _failure_event()
    canary = uuid.uuid4().hex
    object.__setattr__(event, "reason_code", canary)
    with pytest.raises(InvalidSecurityAuditEventError) as caught:
        await _writer(connection).write(event)
    assert canary not in str(caught.value) + repr(event)
    assert connection.writes == []


@pytest.mark.parametrize(
    "kind", [SecurityEventType.ROLE_CREATED, SecurityEventType.SECURITY_EVENTS_PRUNED]
)
async def test_unapproved_role_and_maintenance_paths_fail_closed(
    kind: SecurityEventType,
) -> None:
    connection = _Connection()
    event = (
        SecurityAuditEvent(
            event_type=kind,
            result=SecurityEventResult.SUCCESS,
            user_id=uuid.uuid7(),
            session_id=uuid.uuid7(),
            membership_id=uuid.uuid7(),
            role_id=uuid.uuid7(),
        )
        if kind is SecurityEventType.ROLE_CREATED
        else SecurityAuditEvent(
            event_type=kind, result=SecurityEventResult.SUCCESS, affected_count=0
        )
    )
    with pytest.raises(SecurityAuditWriteError):
        await _writer(connection).write(event)
    assert connection.writes == []


async def test_database_exception_is_replaced_without_secret_or_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = uuid.uuid4().hex
    failure = DBAPIError("SQL-" + canary, {"secret": canary}, RuntimeError(canary))
    connection = _Connection(failure=failure)
    with pytest.raises(SecurityAuditWriteError) as caught:
        await _writer(connection).write(_failure_event())
    rendered = "".join(traceback.format_exception(caught.value))
    assert str(caught.value) == "Security audit write failed."
    assert caught.value.__suppress_context__ is True
    assert canary not in rendered + repr(caught.value) + caplog.text
    assert len(connection.writes) == 1
