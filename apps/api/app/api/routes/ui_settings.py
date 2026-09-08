"""Thin permission-bound HTTP contracts for persisted UI settings."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.api.authorization_dependencies import require_permission
from app.authorization.contracts import AuthorizationGrant
from app.authorization.permissions import Permission
from app.ui_settings.contracts import StoredUiSettingsPatch, UiSettingKey, UiSettingsPatch
from app.ui_settings.service import EffectiveUiSettings, UiSettingsOrigin, ui_settings_service

router = APIRouter(prefix="/ui-settings", tags=["ui-settings"])
manage_self = require_permission(Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF)
manage_tenant = require_permission(Permission.TENANT_UI_SETTINGS_MANAGE)


class UiSettingsWriteRequest(BaseModel):
    settings: UiSettingsPatch
    expected_version: int | None = Field(ge=1)


class UiSettingsLayerResponse(BaseModel):
    settings: dict[UiSettingKey, str]
    version: int

    @classmethod
    def from_record(cls, record: StoredUiSettingsPatch) -> UiSettingsLayerResponse:
        return cls(settings=record.settings.root, version=record.version)


class EffectiveUiSettingsResponse(BaseModel):
    settings: dict[UiSettingKey, str]
    origins: dict[UiSettingKey, UiSettingsOrigin]
    platform_version: int | None
    tenant_version: int | None
    user_version: int | None

    @classmethod
    def from_result(cls, result: EffectiveUiSettings) -> EffectiveUiSettingsResponse:
        return cls.model_validate(result, from_attributes=True)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/effective", response_model=EffectiveUiSettingsResponse)
async def get_effective(
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(manage_self)],
) -> EffectiveUiSettingsResponse:
    _no_store(response)
    return EffectiveUiSettingsResponse.from_result(await ui_settings_service.resolve(grant))


@router.get("/user", response_model=UiSettingsLayerResponse)
async def get_user(
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(manage_self)],
) -> UiSettingsLayerResponse:
    _no_store(response)
    return UiSettingsLayerResponse.from_record(await ui_settings_service.get_user(grant))


@router.put("/user", response_model=UiSettingsLayerResponse)
async def put_user(
    payload: UiSettingsWriteRequest,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(manage_self)],
) -> UiSettingsLayerResponse:
    _no_store(response)
    record = await ui_settings_service.put_user(
        grant, grant.principal.user_id, payload.settings, payload.expected_version
    )
    return UiSettingsLayerResponse.from_record(record)


@router.delete("/user", status_code=204)
async def delete_user(
    expected_version: int,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(manage_self)],
) -> None:
    _no_store(response)
    await ui_settings_service.delete_user(grant, grant.principal.user_id, expected_version)


@router.get("/tenant", response_model=UiSettingsLayerResponse)
async def get_tenant(
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(manage_tenant)],
) -> UiSettingsLayerResponse:
    _no_store(response)
    return UiSettingsLayerResponse.from_record(await ui_settings_service.get_tenant(grant))


@router.put("/tenant", response_model=UiSettingsLayerResponse)
async def put_tenant(
    payload: UiSettingsWriteRequest,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(manage_tenant)],
) -> UiSettingsLayerResponse:
    _no_store(response)
    return UiSettingsLayerResponse.from_record(
        await ui_settings_service.put_tenant(grant, payload.settings, payload.expected_version)
    )


@router.delete("/tenant", status_code=204)
async def delete_tenant(
    expected_version: int,
    response: Response,
    grant: Annotated[AuthorizationGrant, Depends(manage_tenant)],
) -> None:
    _no_store(response)
    await ui_settings_service.delete_tenant(grant, expected_version)
