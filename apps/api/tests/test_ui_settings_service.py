from __future__ import annotations

import uuid

import pytest

from app.auth.tenants import AuthenticatedPrincipal
from app.authorization.contracts import AuthorizationBoundaryRequiredError, AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.models.tenant import TenantId
from app.tenancy.context import TenantContext
from app.ui_settings.contracts import (
    StoredUiSettingsPatch,
    UiSettingKey,
    UiSettingsPatch,
    UserUiSettingsScopeError,
)
from app.ui_settings.service import UiSettingsOrigin, UiSettingsService


class MemoryRepository:
    def __init__(self) -> None:
        self.platform: StoredUiSettingsPatch | None = None
        self.tenant: StoredUiSettingsPatch | None = None
        self.users: dict[uuid.UUID, StoredUiSettingsPatch] = {}

    async def read_platform(self) -> StoredUiSettingsPatch | None:
        return self.platform

    async def read_tenant(self, context: TenantContext) -> StoredUiSettingsPatch | None:
        return self.tenant

    async def read_user(
        self, context: TenantContext, user_id: uuid.UUID
    ) -> StoredUiSettingsPatch | None:
        return self.users.get(user_id)

    async def put_user(
        self,
        context: TenantContext,
        user_id: uuid.UUID,
        patch: UiSettingsPatch,
        expected_version: int | None,
    ) -> StoredUiSettingsPatch | None:
        current = self.users.get(user_id)
        if (current is None) != (expected_version is None) or (
            current is not None and current.version != expected_version
        ):
            return None
        result = StoredUiSettingsPatch(patch, 1 if current is None else current.version + 1)
        self.users[user_id] = result
        return result

    async def delete_user(
        self, context: TenantContext, user_id: uuid.UUID, expected_version: int
    ) -> bool:
        current = self.users.get(user_id)
        if current is None or current.version != expected_version:
            return False
        del self.users[user_id]
        return True

    async def put_tenant(
        self, context: TenantContext, patch: UiSettingsPatch, expected_version: int | None
    ) -> StoredUiSettingsPatch | None:
        current = self.tenant
        if (current is None) != (expected_version is None) or (
            current is not None and current.version != expected_version
        ):
            return None
        self.tenant = StoredUiSettingsPatch(patch, 1 if current is None else current.version + 1)
        return self.tenant

    async def delete_tenant(self, context: TenantContext, expected_version: int) -> bool:
        if self.tenant is None or self.tenant.version != expected_version:
            return False
        self.tenant = None
        return True


def grant(permission: Permission, *, user_id: uuid.UUID | None = None) -> AuthorizationGrant:
    user_id = user_id or uuid.uuid7()
    tenant_id = uuid.uuid7()
    return AuthorizationGrant(
        AuthenticatedPrincipal(user_id, uuid.uuid4(), uuid.uuid4(), 1),
        TenantContext(TenantId(tenant_id)),
        PermissionId(permission.value),
    )


@pytest.mark.asyncio
async def test_effective_resolution_precedence_partial_patches_and_origins() -> None:
    repository = MemoryRepository()
    access = grant(Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF)
    repository.platform = StoredUiSettingsPatch(
        UiSettingsPatch.model_validate({"theme": "sand-warm", "printPreset": "ink-saving"}), 4
    )
    repository.tenant = StoredUiSettingsPatch(
        UiSettingsPatch.model_validate(
            {"theme": "navy-institutional", "tablePreset": "compact-rows"}
        ),
        2,
    )
    repository.users[access.principal.user_id] = StoredUiSettingsPatch(
        UiSettingsPatch.model_validate({"theme": "green-institutional"}), 3
    )

    effective = await UiSettingsService(repository).resolve(access)  # type: ignore[arg-type]

    assert effective.settings[UiSettingKey.THEME] == "green-institutional"
    assert effective.origins[UiSettingKey.THEME] == UiSettingsOrigin.USER
    assert effective.origins[UiSettingKey.TABLE_PRESET] == UiSettingsOrigin.TENANT
    assert effective.origins[UiSettingKey.PRINT_PRESET] == UiSettingsOrigin.PLATFORM
    assert effective.origins[UiSettingKey.ALERT_PRESET] == UiSettingsOrigin.BUILT_IN
    assert (effective.platform_version, effective.tenant_version, effective.user_version) == (
        4,
        2,
        3,
    )


@pytest.mark.asyncio
async def test_deleting_layer_restores_inheritance_without_copying_values() -> None:
    repository = MemoryRepository()
    access = grant(Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF)
    repository.platform = StoredUiSettingsPatch(
        UiSettingsPatch.model_validate({"theme": "sand-warm"}), 1
    )
    repository.tenant = StoredUiSettingsPatch(
        UiSettingsPatch.model_validate({"theme": "navy-institutional"}), 1
    )
    repository.users[access.principal.user_id] = StoredUiSettingsPatch(
        UiSettingsPatch.model_validate({"theme": "green-institutional"}), 1
    )
    service = UiSettingsService(repository)  # type: ignore[arg-type]
    await service.delete_user(access, access.principal.user_id, 1)
    assert (await service.resolve(access)).origins[UiSettingKey.THEME] == UiSettingsOrigin.TENANT

    tenant_access = AuthorizationGrant(
        access.principal,
        access.tenant_context,
        PermissionId(Permission.TENANT_UI_SETTINGS_MANAGE.value),
    )
    await service.delete_tenant(tenant_access, 1)
    assert (await service.resolve(access)).origins[UiSettingKey.THEME] == UiSettingsOrigin.PLATFORM


@pytest.mark.asyncio
async def test_writes_require_exact_permission_and_self_identity() -> None:
    repository = MemoryRepository()
    access = grant(Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF)
    service = UiSettingsService(repository)  # type: ignore[arg-type]
    patch = UiSettingsPatch.model_validate({"theme": "sand-warm"})
    with pytest.raises(UserUiSettingsScopeError):
        await service.put_user(access, uuid.uuid7(), patch, None)
    wrong = AuthorizationGrant(
        access.principal, access.tenant_context, PermissionId(Permission.TENANT_ROLES_READ.value)
    )
    with pytest.raises(AuthorizationBoundaryRequiredError):
        await service.put_user(wrong, access.principal.user_id, patch, None)
    with pytest.raises(AuthorizationBoundaryRequiredError):
        await service.put_tenant(access, patch, None)


def test_platform_write_path_is_not_available() -> None:
    assert not hasattr(UiSettingsService, "put_platform")
    assert not hasattr(MemoryRepository, "put_platform")
