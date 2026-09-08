"""Permission-aware UI-setting writes and deterministic effective resolution."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.authorization.contracts import AuthorizationBoundaryRequiredError, AuthorizationGrant
from app.authorization.permissions import Permission, PermissionId
from app.core.errors import AppError
from app.db.ui_settings_repository import (
    StoredUiSettingsPatch,
    UiSettingsRepository,
    ui_settings_repository,
)
from app.ui_settings.contracts import UiSettingKey, UiSettingsPatch, require_self_user


class UiSettingsConflictError(AppError):
    code = "conflict"
    status_code = 409
    message = "UI settings changed; reload them before retrying."


class UiSettingsOrigin(StrEnum):
    USER = "user"
    TENANT = "tenant"
    PLATFORM = "platform"
    BUILT_IN = "built-in"


BUILT_IN_UI_SETTINGS = UiSettingsPatch.model_validate(
    {
        "theme": "teal-calm",
        "buttonPreset": "institutional-standard",
        "alertPreset": "tinted-standard",
        "overlayPreset": "institutional-standard",
        "tablePreset": "institutional-standard",
        "printPreset": "institutional-standard",
    }
)


@dataclass(frozen=True, slots=True)
class EffectiveUiSettings:
    settings: dict[UiSettingKey, str]
    origins: dict[UiSettingKey, UiSettingsOrigin]
    platform_version: int | None
    tenant_version: int | None
    user_version: int | None


def _require_grant(grant: AuthorizationGrant, permission: Permission) -> AuthorizationGrant:
    if not isinstance(grant, AuthorizationGrant) or grant.permission_id != PermissionId(
        permission.value
    ):
        raise AuthorizationBoundaryRequiredError()
    return grant


class UiSettingsService:
    def __init__(self, repository: UiSettingsRepository = ui_settings_repository) -> None:
        self._repository = repository

    async def resolve(self, grant: AuthorizationGrant) -> EffectiveUiSettings:
        grant = _require_grant(grant, Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF)
        platform, tenant, user = await asyncio.gather(
            self._repository.read_platform(),
            self._repository.read_tenant(grant.tenant_context),
            self._repository.read_user(grant.tenant_context, grant.principal.user_id),
        )
        values = dict(BUILT_IN_UI_SETTINGS.root)
        origins = dict.fromkeys(values, UiSettingsOrigin.BUILT_IN)
        for layer, origin in (
            (platform, UiSettingsOrigin.PLATFORM),
            (tenant, UiSettingsOrigin.TENANT),
            (user, UiSettingsOrigin.USER),
        ):
            if layer:
                for key, value in layer.settings.root.items():
                    values[key], origins[key] = value, origin
        return EffectiveUiSettings(
            values, origins, self._version(platform), self._version(tenant), self._version(user)
        )

    async def put_user(
        self,
        grant: AuthorizationGrant,
        target_user_id: uuid.UUID,
        patch: UiSettingsPatch,
        expected_version: int | None,
    ) -> StoredUiSettingsPatch:
        grant = _require_grant(grant, Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF)
        require_self_user(grant.principal.user_id, target_user_id)
        result = await self._repository.put_user(
            grant.tenant_context, target_user_id, patch, expected_version
        )
        return self._changed(result)

    async def delete_user(
        self, grant: AuthorizationGrant, target_user_id: uuid.UUID, expected_version: int
    ) -> None:
        grant = _require_grant(grant, Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF)
        require_self_user(grant.principal.user_id, target_user_id)
        if not await self._repository.delete_user(
            grant.tenant_context, target_user_id, expected_version
        ):
            raise UiSettingsConflictError()

    async def put_tenant(
        self, grant: AuthorizationGrant, patch: UiSettingsPatch, expected_version: int | None
    ) -> StoredUiSettingsPatch:
        grant = _require_grant(grant, Permission.TENANT_UI_SETTINGS_MANAGE)
        return self._changed(
            await self._repository.put_tenant(grant.tenant_context, patch, expected_version)
        )

    async def delete_tenant(self, grant: AuthorizationGrant, expected_version: int) -> None:
        grant = _require_grant(grant, Permission.TENANT_UI_SETTINGS_MANAGE)
        if not await self._repository.delete_tenant(grant.tenant_context, expected_version):
            raise UiSettingsConflictError()

    @staticmethod
    def _changed(result: StoredUiSettingsPatch | None) -> StoredUiSettingsPatch:
        if result is None:
            raise UiSettingsConflictError()
        return result

    @staticmethod
    def _version(result: StoredUiSettingsPatch | None) -> int | None:
        return None if result is None else result.version


ui_settings_service = UiSettingsService()
