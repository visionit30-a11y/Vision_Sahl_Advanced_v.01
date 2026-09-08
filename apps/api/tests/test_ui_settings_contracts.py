"""Typed UI settings patch and permission catalogue contracts."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.authorization.permissions import PERMISSION_CATALOG, Permission, PermissionId
from app.ui_settings.contracts import (
    UI_SETTINGS_SCHEMA_VERSION,
    UiSettingKey,
    UiSettingsPatch,
    UserUiSettingsScopeError,
    require_self_user,
)


def test_valid_partial_patch_is_normalized() -> None:
    patch = UiSettingsPatch.model_validate(
        {"theme": "sand-warm", "buttonPreset": "compact-sharp"}
    )
    assert patch.as_json() == {"theme": "sand-warm", "buttonPreset": "compact-sharp"}
    assert set(patch.root) == {UiSettingKey.THEME, UiSettingKey.BUTTON_PRESET}
    assert UI_SETTINGS_SCHEMA_VERSION == 1


@pytest.mark.parametrize(
    "value",
    [
        {"unknown": "sand-warm"},
        {"theme": "removed-theme"},
        {"theme": None},
        {"theme": {"raw": "blob"}},
        ["sand-warm"],
    ],
)
def test_unknown_keys_invalid_values_and_arbitrary_json_are_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        UiSettingsPatch.model_validate(value)


def test_user_scope_accepts_self_and_rejects_another_user() -> None:
    user_a, user_b = uuid.uuid7(), uuid.uuid7()
    require_self_user(user_a, user_a)
    with pytest.raises(UserUiSettingsScopeError):
        require_self_user(user_a, user_b)


def test_ui_permissions_are_typed_catalog_members() -> None:
    expected = {
        Permission.TENANT_USER_UI_SETTINGS_MANAGE_SELF,
        Permission.TENANT_UI_SETTINGS_MANAGE,
        Permission.PLATFORM_UI_SETTINGS_MANAGE,
    }
    assert {PermissionId(item.value) for item in expected} <= PERMISSION_CATALOG
    assert Permission.PLATFORM_UI_SETTINGS_MANAGE.value.startswith("platform.")
