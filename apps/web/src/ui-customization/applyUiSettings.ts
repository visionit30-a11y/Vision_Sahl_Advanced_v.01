import type { UiSettings } from './contract/settings';

/**
 * Writes the resolved settings onto the document element. This is the single
 * place the engine touches the DOM: the identity is one attribute, the browser
 * repaints from CSS, and no React component re-renders because of it.
 */
export function applyUiSettings(settings: UiSettings, root: HTMLElement): void {
  root.dataset.theme = settings.theme;
}
