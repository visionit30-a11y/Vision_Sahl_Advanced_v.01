import { readBootstrapUiSettings } from './adapters/browserUiSettingsSource';
import { applyUiSettings } from './applyUiSettings';
import { PREVIEW_TENANT_ID } from './previewTenant';

/**
 * Applies the stored identity before the first paint, so the page never shows
 * one identity for a frame and then swaps to another.
 *
 * Temporary and browser-only, like the storage it reads. In Phase 2 the
 * resolved settings arrive with the application shell instead.
 */
export function bootstrapUiSettings(root: HTMLElement = document.documentElement): void {
  applyUiSettings(readBootstrapUiSettings(PREVIEW_TENANT_ID), root);
}
