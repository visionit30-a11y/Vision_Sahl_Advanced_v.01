"""Closed UI-settings vocabulary shared by persistence and future HTTP boundaries."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Self

from pydantic import RootModel, model_validator

UI_SETTINGS_SCHEMA_VERSION = 1


class ThemeId(StrEnum):
    TEAL_CALM = "teal-calm"
    GREEN_INSTITUTIONAL = "green-institutional"
    NAVY_INSTITUTIONAL = "navy-institutional"
    SLATE_NEUTRAL = "slate-neutral"
    SAND_WARM = "sand-warm"


class ButtonPresetId(StrEnum):
    INSTITUTIONAL_STANDARD = "institutional-standard"
    COMPACT_SHARP = "compact-sharp"
    SOFT_ROUNDED = "soft-rounded"
    OUTLINED_CALM = "outlined-calm"
    BALANCED_ROOMY = "balanced-roomy"


class AlertPresetId(StrEnum):
    TINTED_STANDARD = "tinted-standard"
    SOLID_EMPHATIC = "solid-emphatic"
    MINIMAL_INLINE = "minimal-inline"
    DENSE_COMPACT = "dense-compact"
    BORDERED_QUIET = "bordered-quiet"


class OverlayPresetId(StrEnum):
    INSTITUTIONAL_STANDARD = "institutional-standard"
    SOFT_ELEVATED = "soft-elevated"
    FLAT_BORDERED = "flat-bordered"
    DIM_FOCUSED = "dim-focused"
    COMPACT_DENSE = "compact-dense"


class TablePresetId(StrEnum):
    INSTITUTIONAL_STANDARD = "institutional-standard"
    ZEBRA_SCAN = "zebra-scan"
    FULL_GRID = "full-grid"
    COMPACT_ROWS = "compact-rows"
    AIRY_REPORT = "airy-report"


class PrintPresetId(StrEnum):
    INSTITUTIONAL_STANDARD = "institutional-standard"
    INK_SAVING = "ink-saving"
    HIGH_CONTRAST_PRINT = "high-contrast-print"
    FORMAL_LETTERHEAD = "formal-letterhead"
    DENSE_ARCHIVE = "dense-archive"


class UiSettingKey(StrEnum):
    THEME = "theme"
    BUTTON_PRESET = "buttonPreset"
    ALERT_PRESET = "alertPreset"
    OVERLAY_PRESET = "overlayPreset"
    TABLE_PRESET = "tablePreset"
    PRINT_PRESET = "printPreset"


SETTING_VALUES: dict[UiSettingKey, frozenset[str]] = {
    UiSettingKey.THEME: frozenset(item.value for item in ThemeId),
    UiSettingKey.BUTTON_PRESET: frozenset(item.value for item in ButtonPresetId),
    UiSettingKey.ALERT_PRESET: frozenset(item.value for item in AlertPresetId),
    UiSettingKey.OVERLAY_PRESET: frozenset(item.value for item in OverlayPresetId),
    UiSettingKey.TABLE_PRESET: frozenset(item.value for item in TablePresetId),
    UiSettingKey.PRINT_PRESET: frozenset(item.value for item in PrintPresetId),
}


class UiSettingsPatch(RootModel[dict[UiSettingKey, str]]):
    """A partial, closed patch; absent keys inherit and arbitrary JSON is rejected."""

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        for key, value in self.root.items():
            if type(value) is not str or value not in SETTING_VALUES[key]:
                raise ValueError(f"Invalid value for UI setting {key.value}.")
        return self

    def as_json(self) -> dict[str, str]:
        return {key.value: value for key, value in self.root.items()}


class UserUiSettingsScopeError(ValueError):
    """Raised when a caller tries to target another user's settings."""


def require_self_user(authenticated_user_id: uuid.UUID, target_user_id: uuid.UUID) -> None:
    """Keep user selectors from becoming proof before any persistence service exists."""
    if authenticated_user_id != target_user_id:
        raise UserUiSettingsScopeError("User UI settings may only target the authenticated user.")
