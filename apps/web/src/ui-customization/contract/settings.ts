export const THEME_IDS = [
  'teal-calm',
  'green-institutional',
  'navy-institutional',
  'slate-neutral',
  'sand-warm',
] as const;

export type ThemeId = (typeof THEME_IDS)[number];

/**
 * Everything the customisation engine can decide. Later phases add their own
 * keys here (button, alert, overlay, table and print presets); the resolution
 * engine and the adapters need no change when they do.
 */
export interface UiSettings {
  theme: ThemeId;
}

export type UiSettingsPatch = Partial<UiSettings>;

/**
 * The layer that always exists. It is what the platform falls back to before
 * anyone has configured anything.
 */
export const BUILT_IN_UI_SETTINGS: UiSettings = {
  theme: 'teal-calm',
};

/**
 * Where a resolved value came from. 'user' is part of the contract from the
 * start and is deliberately not implemented yet: adding it later is passing one
 * more layer, not rebuilding the engine.
 */
export const UI_SCOPES = ['builtIn', 'platform', 'tenant', 'user'] as const;

export type UiScope = (typeof UI_SCOPES)[number];

/** The scope a change is written to. */
export type EditableUiScope = Extract<UiScope, 'platform' | 'tenant'>;

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && (THEME_IDS as readonly string[]).includes(value);
}
