"""Typed backend contracts for persisted UI settings."""

from app.ui_settings.contracts import (
    UI_SETTINGS_SCHEMA_VERSION,
    UiSettingsPatch,
    UserUiSettingsScopeError,
    require_self_user,
)

__all__ = [
    "UI_SETTINGS_SCHEMA_VERSION",
    "UiSettingsPatch",
    "UserUiSettingsScopeError",
    "require_self_user",
]
