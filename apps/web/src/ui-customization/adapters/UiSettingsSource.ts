import type { AuthChange } from '../../auth/client';
import type { EditableUiScope, UiSettings, UiSettingsPatch } from '../contract/settings';
import type { UiSettingsOrigin } from '../resolution/resolveUiSettings';

export interface SettingsLayer {
  settings: UiSettingsPatch;
  version: number;
}
export interface SettingsSnapshot {
  settings: UiSettings;
  origin: UiSettingsOrigin;
  layers: Record<EditableUiScope, SettingsLayer | null>;
  allowed: Record<EditableUiScope, boolean>;
}
/** No identity selectors: the server resolves cookie identity and membership. */
export interface UiSettingsSource {
  load(): Promise<SettingsSnapshot>;
  write(scope: EditableUiScope, patch: UiSettingsPatch, version: number | null): Promise<void>;
  remove(scope: EditableUiScope, version: number): Promise<void>;
  subscribe(listener: (event: AuthChange) => void): () => void;
}
