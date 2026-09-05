import { PRESET_FAMILIES } from './contract/presets';
import type { UiSettings } from './contract/settings';

/**
 * Writes the resolved settings onto the document element. This is the single
 * place the engine touches the DOM: each decision is one attribute, the browser
 * repaints from CSS, and no React component re-renders because of it.
 */
export function applyUiSettings(settings: UiSettings, root: HTMLElement): void {
  root.dataset.theme = settings.theme;

  for (const family of PRESET_FAMILIES) {
    root.dataset[family.attribute] = settings[family.key];
  }
}
