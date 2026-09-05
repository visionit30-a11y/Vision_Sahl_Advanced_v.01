import { createContext } from 'react';

import type { EditableUiScope, UiSettings, UiSettingsPatch } from './contract/settings';
import type { UiSettingsOrigin } from './resolution/resolveUiSettings';

export interface UiCustomizationValue {
  /** The settings that apply right now, after the layers were resolved. */
  settings: UiSettings;
  /** Where each resolved value came from, so inheritance can be shown. */
  origin: UiSettingsOrigin;
  /** The stored layers themselves, for interfaces that edit them. */
  layers: Readonly<Record<EditableUiScope, UiSettingsPatch | null>>;
  tenantId: string | null;
  /** False while the stored layers are still being read. */
  ready: boolean;
  canManage: (scope: EditableUiScope) => boolean;
  setSetting: <K extends keyof UiSettings>(
    scope: EditableUiScope,
    key: K,
    value: UiSettings[K],
  ) => Promise<void>;
  /** Removes the key from that layer, so the layer beneath it applies again. */
  clearSetting: (scope: EditableUiScope, key: keyof UiSettings) => Promise<void>;
}

export const UiCustomizationContext = createContext<UiCustomizationValue | null>(null);
