import { createContext } from 'react';
import type { EditableUiScope, UiSettings, UiSettingsPatch } from './contract/settings';
import type { UiSettingsOrigin } from './resolution/resolveUiSettings';

export type SettingsStatus =
  'loading' | 'ready' | 'saving' | 'unauthorized' | 'forbidden' | 'conflict' | 'error';
export interface UiCustomizationValue {
  settings: UiSettings;
  origin: UiSettingsOrigin;
  layers: Readonly<Record<EditableUiScope, UiSettingsPatch | null>>;
  ready: boolean;
  status: SettingsStatus;
  reload: () => Promise<void>;
  canManage: (scope: EditableUiScope) => boolean;
  setSetting: <K extends keyof UiSettings>(
    scope: EditableUiScope,
    key: K,
    value: UiSettings[K],
  ) => Promise<void>;
  clearSetting: (scope: EditableUiScope, key: keyof UiSettings) => Promise<void>;
}
export const UiCustomizationContext = createContext<UiCustomizationValue | null>(null);
