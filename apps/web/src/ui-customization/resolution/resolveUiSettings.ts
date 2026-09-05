import { BUILT_IN_UI_SETTINGS, UI_SETTINGS_VALIDATORS } from '../contract/settings';
import type { UiScope, UiSettings, UiSettingsPatch } from '../contract/settings';

export interface UiSettingsLayers {
  builtIn: UiSettings;
  platform?: UiSettingsPatch | null;
  tenant?: UiSettingsPatch | null;
  /**
   * Accepted by the contract from the start and deliberately not supplied in
   * Phase 1B-1. Enabling it later is passing one more layer, not rebuilding the
   * engine.
   */
  user?: UiSettingsPatch | null;
}

export type UiSettingsOrigin = Record<keyof UiSettings, UiScope>;

export interface ResolvedUiSettings {
  settings: UiSettings;
  origin: UiSettingsOrigin;
}

/**
 * The order a value is looked up in: the first layer that holds a usable value
 * wins, and the built-in layer always answers.
 */
const PRECEDENCE: readonly UiScope[] = ['user', 'tenant', 'platform', 'builtIn'];

function layerOf(layers: UiSettingsLayers, scope: UiScope): UiSettingsPatch | null | undefined {
  switch (scope) {
    case 'user':
      return layers.user;
    case 'tenant':
      return layers.tenant;
    case 'platform':
      return layers.platform;
    case 'builtIn':
      return layers.builtIn;
  }
}

/**
 * Resolves the settings that apply right now, and says where each of them came
 * from. Pure: no storage, no DOM, no state — which is what makes the precedence
 * rule testable on its own.
 */
export function resolveUiSettings(layers: UiSettingsLayers): ResolvedUiSettings {
  const keys = Object.keys(layers.builtIn) as (keyof UiSettings)[];
  const settings = {} as UiSettings;
  const origin = {} as UiSettingsOrigin;

  for (const key of keys) {
    for (const scope of PRECEDENCE) {
      const value = layerOf(layers, scope)?.[key];

      if (value !== undefined && UI_SETTINGS_VALIDATORS[key](value)) {
        settings[key] = value;
        origin[key] = scope;
        break;
      }
    }

    if (origin[key] === undefined) {
      // Reached only when the built-in layer itself carries an invalid value.
      settings[key] = BUILT_IN_UI_SETTINGS[key];
      origin[key] = 'builtIn';
    }
  }

  return { settings, origin };
}
