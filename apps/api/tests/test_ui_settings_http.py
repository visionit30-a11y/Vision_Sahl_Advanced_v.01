from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.authorization_dependencies import (
    get_authorization_service,
    require_authenticated_access,
)
from app.auth.sessions import SessionRecord
from app.auth.tenants import AuthenticatedPrincipal, TrustedTenantAccess
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.authorization.service import AuthorizationDecision
from app.models.tenant import TenantId
from app.tenancy.context import TenantContext
from app.ui_settings.contracts import StoredUiSettingsPatch, UiSettingKey, UiSettingsPatch
from app.ui_settings.service import (
    EffectiveUiSettings,
    UiSettingsConflictError,
    UiSettingsNotFoundError,
    UiSettingsOrigin,
    ui_settings_service,
)


@dataclass
class StubAuthorizer:
    decision: AuthorizationDecision
    calls: list[tuple[object, object, object]] = field(default_factory=list)

    async def authorize(
        self, principal: object, context: object, permission: object
    ) -> AuthorizationDecision:
        self.calls.append((principal, context, permission))
        return self.decision


def _access() -> TrustedTenantAccess:
    tenant_id, user_id, session_id, membership_id = (uuid.uuid7() for _ in range(4))
    now = datetime.now(UTC)
    session = SessionRecord(
        session_id,
        user_id,
        bytes([1]) * 32,
        bytes([2]) * 32,
        1,
        now,
        now,
        now,
        now + timedelta(minutes=30),
        now + timedelta(hours=8),
        selected_membership_id=membership_id,
        selected_membership_version=1,
    )
    return TrustedTenantAccess(
        AuthenticatedPrincipal(user_id, session_id, membership_id, 1),
        TenantContext(TenantId(tenant_id)),
        session,
    )


def _authorize(
    app: FastAPI,
    access: TrustedTenantAccess,
    decision: AuthorizationDecision = AuthorizationDecision.ALLOW,
) -> StubAuthorizer:
    authorizer = StubAuthorizer(decision)

    async def trusted() -> TrustedTenantAccess:
        return access

    app.dependency_overrides[require_authenticated_access] = trusted
    app.dependency_overrides[get_authorization_service] = lambda: authorizer
    return authorizer


@pytest.mark.asyncio
async def test_effective_read_is_authenticated_typed_and_no_store(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    access = _access()
    authorizer = _authorize(app, access)

    async def resolve(_grant: AuthorizationGrant) -> EffectiveUiSettings:
        settings = dict.fromkeys(UiSettingKey, "institutional-standard")
        settings[UiSettingKey.THEME] = "teal-calm"
        settings[UiSettingKey.ALERT_PRESET] = "tinted-standard"
        origins = dict.fromkeys(settings, UiSettingsOrigin.BUILT_IN)
        return EffectiveUiSettings(settings, origins, None, None, None)

    monkeypatch.setattr(type(ui_settings_service), "resolve", lambda self, grant: resolve(grant))
    response = await client.get("/ui-settings/effective")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["origins"]["theme"] == "built-in"
    assert authorizer.calls[0][2] == PermissionId(
        Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF.value
    )


@pytest.mark.asyncio
async def test_missing_session_and_missing_permission_are_denied(
    app: FastAPI, client: AsyncClient
) -> None:
    missing = await client.get("/ui-settings/effective")
    assert missing.status_code == 401
    assert missing.headers["cache-control"] == "no-store"
    _authorize(app, _access(), AuthorizationDecision.DENY)
    denied = await client.get("/ui-settings/effective")
    assert denied.status_code == 403
    assert denied.headers["cache-control"] == "no-store"
    assert "permission" not in denied.text.lower()


@pytest.mark.asyncio
async def test_user_endpoints_can_only_target_current_principal(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    access = _access()
    _authorize(app, access)
    calls: list[tuple[str, object]] = []
    record = StoredUiSettingsPatch(UiSettingsPatch.model_validate({"theme": "sand-warm"}), 2)

    async def get_user(_grant: AuthorizationGrant) -> StoredUiSettingsPatch:
        calls.append(("get", access.principal.user_id))
        return record

    async def put_user(
        _grant: AuthorizationGrant,
        user_id: uuid.UUID,
        _patch: UiSettingsPatch,
        expected: int | None,
    ) -> StoredUiSettingsPatch:
        calls.append(("put", user_id))
        assert expected == 1
        return record

    async def delete_user(_grant: AuthorizationGrant, user_id: uuid.UUID, expected: int) -> None:
        calls.append(("delete", user_id))
        assert expected == 2

    monkeypatch.setattr(type(ui_settings_service), "get_user", lambda self, grant: get_user(grant))
    monkeypatch.setattr(
        type(ui_settings_service),
        "put_user",
        lambda self, grant, user_id, patch, expected: put_user(grant, user_id, patch, expected),
    )
    monkeypatch.setattr(
        type(ui_settings_service),
        "delete_user",
        lambda self, grant, user_id, expected: delete_user(grant, user_id, expected),
    )
    assert (await client.get("/ui-settings/user?user_id=" + str(uuid.uuid7()))).status_code == 200
    updated = await client.put(
        "/ui-settings/user",
        json={
            "settings": {"theme": "sand-warm"},
            "expected_version": 1,
            "user_id": str(uuid.uuid7()),
            "tenant_id": str(uuid.uuid7()),
        },
    )
    assert updated.status_code == 200 and updated.json()["version"] == 2
    deleted = await client.delete("/ui-settings/user?expected_version=2")
    assert deleted.status_code == 204
    assert all(value == access.principal.user_id for _, value in calls)


@pytest.mark.asyncio
async def test_tenant_endpoints_use_context_and_increment_versions(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    access = _access()
    authorizer = _authorize(app, access)
    first = StoredUiSettingsPatch(UiSettingsPatch.model_validate({"theme": "sand-warm"}), 1)
    second = StoredUiSettingsPatch(UiSettingsPatch.model_validate({"theme": "teal-calm"}), 2)

    async def get_tenant(grant: AuthorizationGrant) -> StoredUiSettingsPatch:
        assert grant.tenant_context == access.context
        return first

    async def put_tenant(
        grant: AuthorizationGrant, _patch: UiSettingsPatch, expected: int | None
    ) -> StoredUiSettingsPatch:
        assert grant.tenant_context == access.context and expected == 1
        return second

    async def delete_tenant(grant: AuthorizationGrant, expected: int) -> None:
        assert grant.tenant_context == access.context and expected == 2

    monkeypatch.setattr(
        type(ui_settings_service), "get_tenant", lambda self, grant: get_tenant(grant)
    )
    monkeypatch.setattr(
        type(ui_settings_service),
        "put_tenant",
        lambda self, grant, patch, expected: put_tenant(grant, patch, expected),
    )
    monkeypatch.setattr(
        type(ui_settings_service),
        "delete_tenant",
        lambda self, grant, expected: delete_tenant(grant, expected),
    )
    assert (
        await client.get("/ui-settings/tenant", headers={"X-Tenant-ID": str(uuid.uuid7())})
    ).status_code == 200
    response = await client.put(
        "/ui-settings/tenant",
        json={
            "settings": {"theme": "teal-calm"},
            "expected_version": 1,
            "tenant_id": str(uuid.uuid7()),
        },
    )
    assert response.status_code == 200 and response.json()["version"] == 2
    assert (await client.delete("/ui-settings/tenant?expected_version=2")).status_code == 204
    assert all(
        call[2] == PermissionId(Permission.TENANT_UI_SETTINGS_MANAGE.value)
        for call in authorizer.calls
    )


@pytest.mark.asyncio
async def test_validation_conflict_and_absent_platform_write_contract(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorize(app, _access())
    invalid = await client.put(
        "/ui-settings/user", json={"settings": {"theme": "secret-value"}, "expected_version": 1}
    )
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "no-store"
    assert "secret-value" not in invalid.text

    async def conflict(*_args: object) -> object:
        raise UiSettingsConflictError()

    monkeypatch.setattr(type(ui_settings_service), "put_user", conflict)
    stale = await client.put(
        "/ui-settings/user", json={"settings": {"theme": "sand-warm"}, "expected_version": 8}
    )
    assert stale.status_code == 409
    assert stale.headers["cache-control"] == "no-store"
    assert (await client.put("/ui-settings/platform", json={})).status_code == 404

    async def missing(*_args: object) -> object:
        raise UiSettingsNotFoundError()

    monkeypatch.setattr(type(ui_settings_service), "get_user", missing)
    absent = await client.get("/ui-settings/user")
    assert absent.status_code == 404
    assert absent.headers["cache-control"] == "no-store"


def test_routes_expose_no_selectors_repository_or_platform_write() -> None:
    route = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "routes" / "ui_settings.py"
    ).read_text(encoding="utf-8")
    assert "app.db" not in route
    assert "tenant_id" not in route
    assert "target_user_id" not in route
    assert '@router.put("/platform"' not in route
    assert '@router.delete("/platform"' not in route
    assert "Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF" in route
    assert "Permission.TENANT_UI_SETTINGS_MANAGE" in route
