import type { UiSettingsPatch } from '../contract/settings';

/**
 * Where the customisation layers are stored.
 *
 * Asynchronous from day one although the Phase 1B-1 implementation reads the
 * browser synchronously: the Phase 2 implementation is an HTTP call, and
 * turning a synchronous interface asynchronous later would touch every caller.
 *
 * Write semantics: a write replaces the whole layer with the patch it is given.
 * Merging is the caller's decision, which is what lets a key be removed to fall
 * back to the layer beneath it.
 */
export interface UiSettingsSource {
  readPlatform(): Promise<UiSettingsPatch | null>;
  readTenant(tenantId: string | null): Promise<UiSettingsPatch | null>;
  writePlatform(patch: UiSettingsPatch): Promise<void>;
  writeTenant(tenantId: string | null, patch: UiSettingsPatch): Promise<void>;
}
