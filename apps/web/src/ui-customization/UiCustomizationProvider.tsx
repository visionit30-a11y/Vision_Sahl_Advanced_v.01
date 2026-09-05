import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { applyUiSettings } from './applyUiSettings';
import { BUILT_IN_UI_SETTINGS } from './contract/settings';
import type { EditableUiScope, UiSettings, UiSettingsPatch } from './contract/settings';
import { browserUiSettingsSource } from './adapters/browserUiSettingsSource';
import { previewUiPermissions } from './adapters/previewUiPermissions';
import type { UiPermissions } from './adapters/UiPermissions';
import type { UiSettingsSource } from './adapters/UiSettingsSource';
import { PREVIEW_TENANT_ID } from './previewTenant';
import { resolveUiSettings } from './resolution/resolveUiSettings';
import { UiCustomizationContext } from './UiCustomizationContext';
import type { UiCustomizationValue } from './UiCustomizationContext';

type Layers = Record<EditableUiScope, UiSettingsPatch | null>;

const EMPTY_LAYERS: Layers = { platform: null, tenant: null };

export interface UiCustomizationProviderProps {
  children: ReactNode;
  /** Injected in tests; the browser implementation is the default. */
  source?: UiSettingsSource;
  /** Injected in tests; the preview stub is the default. */
  permissions?: UiPermissions;
  /** A preview fixture in Phase 1B-1, replaced by real tenancy in Phase 2. */
  tenantId?: string | null;
}

export function UiCustomizationProvider({
  children,
  source = browserUiSettingsSource,
  permissions = previewUiPermissions,
  tenantId = PREVIEW_TENANT_ID,
}: UiCustomizationProviderProps) {
  const [layers, setLayers] = useState<Layers>(EMPTY_LAYERS);
  const [ready, setReady] = useState(false);
  const layersRef = useRef(layers);
  layersRef.current = layers;

  useEffect(() => {
    let active = true;

    async function load() {
      const [platform, tenant] = await Promise.all([
        source.readPlatform(),
        source.readTenant(tenantId),
      ]);

      if (active) {
        setLayers({ platform, tenant });
        setReady(true);
      }
    }

    void load();

    return () => {
      active = false;
    };
  }, [source, tenantId]);

  const resolved = useMemo(
    () =>
      resolveUiSettings({
        builtIn: BUILT_IN_UI_SETTINGS,
        platform: layers.platform,
        tenant: layers.tenant,
      }),
    [layers],
  );

  const settings = resolved.settings;

  // Applied before paint so the identity never shows for a frame and then swaps.
  useLayoutEffect(() => {
    applyUiSettings(settings, document.documentElement);
  }, [settings]);

  const canManage = useCallback(
    (scope: EditableUiScope) =>
      scope === 'platform' ? permissions.canManagePlatformUi() : permissions.canManageTenantUi(),
    [permissions],
  );

  const persist = useCallback(
    async (scope: EditableUiScope, next: UiSettingsPatch) => {
      // The permission layer answers here so that no screen has to ask twice.
      // It is a seam, not a security control: Phase 2 enforces this on the API.
      if (!canManage(scope)) {
        return;
      }

      setLayers((current) => ({ ...current, [scope]: next }));

      if (scope === 'platform') {
        await source.writePlatform(next);
      } else {
        await source.writeTenant(tenantId, next);
      }
    },
    [canManage, source, tenantId],
  );

  const setSetting = useCallback(
    <K extends keyof UiSettings>(scope: EditableUiScope, key: K, value: UiSettings[K]) =>
      persist(scope, { ...(layersRef.current[scope] ?? {}), [key]: value }),
    [persist],
  );

  const clearSetting = useCallback(
    (scope: EditableUiScope, key: keyof UiSettings) => {
      const next = { ...(layersRef.current[scope] ?? {}) };
      delete next[key];
      return persist(scope, next);
    },
    [persist],
  );

  const value = useMemo<UiCustomizationValue>(
    () => ({
      settings,
      origin: resolved.origin,
      layers,
      tenantId,
      ready,
      canManage,
      setSetting,
      clearSetting,
    }),
    [settings, resolved.origin, layers, tenantId, ready, canManage, setSetting, clearSetting],
  );

  return (
    <UiCustomizationContext.Provider value={value}>{children}</UiCustomizationContext.Provider>
  );
}
