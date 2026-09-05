import { isAlertPresetId, isButtonPresetId, isOverlayPresetId } from './presets';
import type { AlertPresetId, ButtonPresetId, OverlayPresetId } from './presets';

export const THEME_IDS = [
  'teal-calm',
  'green-institutional',
  'navy-institutional',
  'slate-neutral',
  'sand-warm',
] as const;

export type ThemeId = (typeof THEME_IDS)[number];

/**
 * Everything the customisation engine can decide. The identity settles colour;
 * the three presentation families settle form. Later phases add their own keys
 * here (table and print presets); the resolution engine and the adapters need
 * no change when they do.
 */
export interface UiSettings {
  theme: ThemeId;
  buttonPreset: ButtonPresetId;
  alertPreset: AlertPresetId;
  overlayPreset: OverlayPresetId;
  tablePreset: TablePresetId;
  printPreset: PrintPresetId;
}

export type UiSettingsPatch = Partial<UiSettings>;

/**
 * The layer that always exists. It is what the platform falls back to before
 * anyone has configured anything, and every value here is the shape the
 * application already had: installing this phase changes nothing on screen
 * until someone chooses otherwise.
 */
export const BUILT_IN_UI_SETTINGS: UiSettings = {
  theme: 'teal-calm',
  buttonPreset: 'institutional-standard',
  alertPreset: 'tinted-standard',
  overlayPreset: 'institutional-standard',
  tablePreset: 'institutional-standard',
  printPreset: 'institutional-standard',
};

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && (THEME_IDS as readonly string[]).includes(value);
}

/**
 * One validator per setting, in one place.
 *
 * A stored value is untrusted input: it may come from an older release that
 * knew other identifiers. Both the resolution engine and the storage adapter
 * read this table, so neither can drift from the other, and adding a setting
 * is one entry rather than two edits that must agree.
 */
export const UI_SETTINGS_VALIDATORS: {
  [K in keyof UiSettings]: (value: unknown) => value is UiSettings[K];
} = {
  theme: isThemeId,
  buttonPreset: isButtonPresetId,
  alertPreset: isAlertPresetId,
  overlayPreset: isOverlayPresetId,
  tablePreset: isTablePresetId,
  printPreset: isPrintPresetId,
};

export const UI_SETTING_KEYS = Object.keys(UI_SETTINGS_VALIDATORS) as (keyof UiSettings)[];

/**
 * Where a resolved value came from. 'user' is part of the contract from the
 * start and is deliberately not implemented yet: adding it later is passing one
 * more layer, not rebuilding the engine.
 */
export const UI_SCOPES = ['builtIn', 'platform', 'tenant', 'user'] as const;

export type UiScope = (typeof UI_SCOPES)[number];

/** The scope a change is written to. */
export type EditableUiScope = Extract<UiScope, 'platform' | 'tenant'>;
