import {
  BUILT_IN_UI_SETTINGS,
  UI_SETTINGS_VALIDATORS,
  UI_SETTING_KEYS,
} from '../contract/settings';
import type { UiSettings, UiSettingsPatch } from '../contract/settings';
import { resolveUiSettings } from '../resolution/resolveUiSettings';
import type { UiSettingsSource } from './UiSettingsSource';

/**
 * A temporary implementation that keeps the layers in browser storage.
 *
 * Phase 1B-1 has no backend, no settings table and no tenancy, so this stands
 * in for them. It is the ONLY place in the application that reads or writes
 * customisation storage; a guard keeps components away from it. Phase 2
 * replaces this file with an HTTP implementation and nothing else changes.
 *
 * Storage may be unavailable or full. Every failure degrades to "no stored
 * layer" rather than breaking the interface: the setting still applies for the
 * current visit.
 */
const PLATFORM_KEY = 'sahl.ui.platform';
const TENANT_KEY_PREFIX = 'sahl.ui.tenant.';

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** Storage holds untrusted text: anything unreadable is treated as absent. */
function readKey(key: string): UiSettingsPatch | null {
  const store = storage();
  if (!store) {
    return null;
  }

  try {
    const raw = store.getItem(key);
    if (!raw) {
      return null;
    }

    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) {
      return null;
    }

    const stored = parsed as Record<string, unknown>;
    const patch: UiSettingsPatch = {};

    for (const key of UI_SETTING_KEYS) {
      const value = stored[key];
      if (UI_SETTINGS_VALIDATORS[key](value)) {
        // The validator has narrowed the value for this key, but TypeScript
        // cannot carry that narrowing through a key it only knows as a union.
        (patch as Record<string, unknown>)[key] = value;
      }
    }

    return patch;
  } catch {
    return null;
  }
}

function writeKey(key: string, patch: UiSettingsPatch): void {
  const store = storage();
  if (!store) {
    return;
  }

  try {
    if (Object.keys(patch).length === 0) {
      store.removeItem(key);
      return;
    }

    store.setItem(key, JSON.stringify(patch));
  } catch {
    // A browser that refuses storage must not break customisation.
  }
}

function tenantKey(tenantId: string): string {
  return `${TENANT_KEY_PREFIX}${tenantId}`;
}

export const browserUiSettingsSource: UiSettingsSource = {
  readPlatform: () => Promise.resolve(readKey(PLATFORM_KEY)),
  readTenant: (tenantId) => Promise.resolve(tenantId ? readKey(tenantKey(tenantId)) : null),
  writePlatform: (patch) => {
    writeKey(PLATFORM_KEY, patch);
    return Promise.resolve();
  },
  writeTenant: (tenantId, patch) => {
    if (tenantId) {
      writeKey(tenantKey(tenantId), patch);
    }
    return Promise.resolve();
  },
};

/**
 * Resolves the stored layers synchronously, once, before the first paint.
 *
 * Not part of UiSettingsSource: it exists only because browser storage happens
 * to be synchronous, and it disappears with this file in Phase 2. Without it
 * the first frame would paint the built-in identity and then swap, which reads
 * as a flicker to anyone who chose another identity.
 */
export function readBootstrapUiSettings(tenantId: string | null): UiSettings {
  const { settings } = resolveUiSettings({
    builtIn: BUILT_IN_UI_SETTINGS,
    platform: readKey(PLATFORM_KEY),
    tenant: tenantId ? readKey(tenantKey(tenantId)) : null,
  });

  return settings;
}
