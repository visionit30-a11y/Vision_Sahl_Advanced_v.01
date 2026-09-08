import { applyUiSettings } from './applyUiSettings';
import { BUILT_IN_UI_SETTINGS } from './contract/settings';

/** Temporary presentation while authenticated server settings are loading. */
export function bootstrapUiSettings(root: HTMLElement = document.documentElement): void {
  applyUiSettings(BUILT_IN_UI_SETTINGS, root);
}
