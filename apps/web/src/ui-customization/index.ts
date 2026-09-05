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
export { UI_SCOPES } from './contract/settings';
export type {
  EditableUiScope,
  ThemeId,
  UiScope,
  UiSettings,
  UiSettingsPatch,
} from './contract/settings';
export { PREVIEW_TENANT_ID } from './previewTenant';
