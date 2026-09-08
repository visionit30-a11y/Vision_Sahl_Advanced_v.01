"""Live database proofs for durable denial events on existing auth HTTP flows."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.audit import request_events
from app.audit.request_events import SecurityDenialAuditor
from app.audit.writer import SecurityAuditWriteError, SecurityEventWriter
from app.auth.http import CsrfRejectedError, TenantContextChangedError
from app.auth.tenants import AuthenticatedPrincipal, TenantAccessDeniedError
from app.authorization.permissions import Permission, PermissionId
from app.core.config import Settings, get_settings
from app.core.context import (
    bind_request_context,
    clear_request_context,
    get_internal_correlation_id,
)
from app.db import auth_http
from tests.db.test_auth_transport_db import TransportFixture

pytest_plugins = ("tests.db.test_auth_transport_db",)


@pytest.fixture
def settings() -> Settings:
    # The imported async fixture is also runnable without collecting its source module.
    return get_settings()


def _events(data: TransportFixture) -> list[dict[str, object]]:
    with data.migrator.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text("SELECT * FROM auth.security_events WHERE user_id=:user ORDER BY id"),
                {"user": data.user},
            ).mappings()
        ]


async def test_membership_denial_is_committed_without_trusting_selected_target(
    transport_fixture: TransportFixture,
) -> None:
    data = transport_fixture
    with data.migrator.begin() as connection:
        connection.execute(
            text("UPDATE auth.tenant_memberships SET status='suspended' WHERE id=:id"),
            {"id": data.memberships[0]},
        )
    with pytest.raises(TenantAccessDeniedError):
        await data.service.me(data.issued.secrets.bearer)
    rows = _events(data)
    assert len(rows) == 1 and rows[0]["event_type"] == "membership_denied"
    assert rows[0]["session_id"] == data.issued.record.id
    assert rows[0]["membership_id"] is None and rows[0]["target_membership_id"] is None


@pytest.mark.parametrize("failure", ["missing", "invalid", "origin", "stale"])
async def test_unsafe_denial_persists_once_after_rollback(
    transport_fixture: TransportFixture, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    data = transport_fixture
    monkeypatch.setattr(request_events, "get_settings", lambda: data.settings)
    request = data.request(data.issued.secrets.csrf_token, data.memberships[0])
    headers = [
        (k, v)
        for k, v in request.scope["headers"]
        if not (failure == "missing" and k == b"x-csrf-token")
    ]
    key = {
        "invalid": b"x-csrf-token",
        "origin": b"origin",
        "stale": b"x-expected-membership-id",
    }.get(failure)
    value = str(uuid.uuid7()).encode() if failure == "stale" else b"canary-denied-request-secret"
    request.scope["headers"] = [(k, value if k == key else v) for k, v in headers]
    expected = TenantContextChangedError if failure == "stale" else CsrfRejectedError
    with pytest.raises(expected):
        await data.service.logout(data.issued.secrets.bearer, request)
    rows = _events(data)
    assert len(rows) == 1
    assert rows[0]["event_type"] == {"origin": "origin_rejected", "stale": "membership_denied"}.get(
        failure, "csrf_rejected"
    )
    assert rows[0]["membership_id"] is None
    assert "canary-denied-request-secret" not in repr(rows)
    with data.migrator.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT revoked_at FROM auth.sessions WHERE id=:id"),
                {"id": data.issued.record.id},
            )
            is None
        )


async def test_denial_audit_outage_never_allows_request(
    transport_fixture: TransportFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = transport_fixture

    async def fail(self: SecurityEventWriter, event: object) -> None:
        raise SecurityAuditWriteError()

    monkeypatch.setattr(SecurityEventWriter, "write", fail)
    with pytest.raises(TenantAccessDeniedError):
        await data.service.switch(
            data.issued.secrets.bearer,
            uuid.uuid7(),
            data.request(data.issued.secrets.csrf_token, data.memberships[0]),
        )
    assert _events(data) == []
    output = capsys.readouterr()
    assert data.issued.secrets.bearer not in output.out + output.err
    assert data.issued.secrets.csrf_token not in output.out + output.err


async def test_authorization_denial_has_trusted_ids_and_internal_correlation(
    transport_fixture: TransportFixture,
) -> None:
    data = transport_fixture
    principal = AuthenticatedPrincipal(data.user, data.issued.record.id, data.memberships[0], 1)
    bind_request_context("canary-client-correlation")
    try:
        correlation = get_internal_correlation_id()
        await SecurityDenialAuditor(auth_http._engine).authorization_denied(
            principal, PermissionId(Permission.TENANT_ROLES_MANAGE.value)
        )
        rows = _events(data)
        assert len(rows) == 1 and rows[0]["event_type"] == "authorization_denied"
        assert rows[0]["membership_id"] == data.memberships[0]
        assert rows[0]["correlation_id"] == str(correlation)
        assert "canary-client-correlation" not in repr(rows)
    finally:
        clear_request_context()


async def test_bootstrap_fetch_metadata_rejection_is_an_origin_event(
    transport_fixture: TransportFixture,
) -> None:
    data = transport_fixture
    request = data.request(data.issued.secrets.csrf_token, data.memberships[0], method="GET")
    request.scope["headers"].append((b"sec-fetch-site", b"cross-site"))
    bind_request_context("bootstrap-public-id")
    try:
        correlation = get_internal_correlation_id()
        await SecurityDenialAuditor(auth_http._engine).request_denied(
            CsrfRejectedError(), request, origin_failure=True
        )
        with data.migrator.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT event_type,reason_code,user_id FROM auth.security_events "
                    "WHERE correlation_id=:id"
                ),
                {"id": str(correlation)},
            ).one()
            assert tuple(row) == ("origin_rejected", "origin_denied", None)
            connection.execute(
                text("DELETE FROM auth.security_events WHERE correlation_id=:id"),
                {"id": str(correlation)},
            )
    finally:
        clear_request_context()
