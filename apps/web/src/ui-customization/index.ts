/**
 * The single entry point of the customisation engine. Screens import from here
 * and never reach into the engine's internals.
 */
export { bootstrapUiSettings } from './bootstrapUiSettings';
export { UiCustomizationProvider } from './UiCustomizationProvider';
export { useUiCustomization } from './useUiCustomization';
export type { UiCustomizationValue } from './UiCustomizationContext';
export { themeRegistry } from './registries/themeRegistry';
export type { ThemeDefinition } from './registries/themeRegistry';
export { buttonPresetRegistry } from './registries/buttonPresetRegistry';
export { alertPresetRegistry } from './registries/alertPresetRegistry';
export { overlayPresetRegistry } from './registries/overlayPresetRegistry';
export type { PresetDefinition } from './registries/createPresetRegistry';
export { PRESET_FAMILIES } from './contract/presets';
export type {
  AlertPresetId,
  ButtonPresetId,
  OverlayPresetId,
  PresetSettingKey,
} from './contract/presets';
export { UI_SCOPES, UI_SETTING_KEYS } from './contract/settings';
export type {
  EditableUiScope,
  ThemeId,
  UiScope,
  UiSettings,
  UiSettingsPatch,
} from './contract/settings';
export { PREVIEW_TENANT_ID } from './previewTenant';
