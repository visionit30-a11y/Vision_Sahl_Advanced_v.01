import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { HttpRequestError, SessionInvalidError } from '../auth/client';
import { applyUiSettings } from './applyUiSettings';
import { BUILT_IN_UI_SETTINGS, UI_SETTING_KEYS } from './contract/settings';
import type { EditableUiScope, UiSettings, UiSettingsPatch } from './contract/settings';
import { httpUiSettingsSource } from './adapters/httpUiSettingsSource';
import type { SettingsSnapshot, UiSettingsSource } from './adapters/UiSettingsSource';
import { UiCustomizationContext } from './UiCustomizationContext';
import type { SettingsStatus, UiCustomizationValue } from './UiCustomizationContext';
import type { UiSettingsOrigin } from './resolution/resolveUiSettings';

const TEMPORARY: SettingsSnapshot = {
  settings: BUILT_IN_UI_SETTINGS,
  origin: Object.fromEntries(UI_SETTING_KEYS.map((key) => [key, 'builtIn'])) as UiSettingsOrigin,
  layers: { user: null, tenant: null },
  allowed: { user: false, tenant: false },
};
function failure(error: unknown): SettingsStatus {
  if (
    error instanceof SessionInvalidError ||
    (error instanceof HttpRequestError && error.status === 401)
  )
    return 'unauthorized';
  if (error instanceof HttpRequestError && error.status === 403) return 'forbidden';
  if (error instanceof HttpRequestError && error.status === 409) return 'conflict';
  return 'error';
}
export interface UiCustomizationProviderProps {
  children: ReactNode;
  source?: UiSettingsSource;
}

export function UiCustomizationProvider({
  children,
  source = httpUiSettingsSource,
}: UiCustomizationProviderProps) {
  const [snapshot, setSnapshot] = useState(TEMPORARY);
  const [status, setStatus] = useState<SettingsStatus>('loading');
  const current = useRef(snapshot);
  current.current = snapshot;
  const sequence = useRef(0);
  const busy = useRef(false);
  const available = useRef(false);

  const reset = useCallback((next: SettingsStatus) => {
    available.current = false;
    current.current = TEMPORARY;
    setSnapshot(TEMPORARY);
    setStatus(next);
  }, []);

  const reload = useCallback(async () => {
    const request = ++sequence.current;
    busy.current = false;
    reset('loading');
    try {
      const next = await source.load();
      if (request !== sequence.current) return;
      current.current = next;
      setSnapshot(next);
      available.current = true;
      setStatus('ready');
    } catch (error) {
      if (request === sequence.current) reset(failure(error));
    }
  }, [source, reset]);

  const invalidate = useCallback(() => {
    ++sequence.current;
    available.current = false;
  }, []);

  useEffect(() => {
    const unsubscribe = source.subscribe((event) => {
      ++sequence.current;
      busy.current = false;
      reset(event === 'invalid' ? 'unauthorized' : 'loading');
      if (event === 'changed') void reload();
    });
    void reload();
    return () => {
      invalidate();
      unsubscribe();
    };
  }, [source, reload, reset, invalidate]);

  useLayoutEffect(() => {
    applyUiSettings(snapshot.settings, document.documentElement);
  }, [snapshot.settings]);

  const persist = useCallback(
    async (scope: EditableUiScope, next: UiSettingsPatch) => {
      if (!available.current || busy.current || !current.current.allowed[scope]) return;
      const request = ++sequence.current;
      const layer = current.current.layers[scope];
      busy.current = true;
      setStatus('saving');
      try {
        if (Object.keys(next).length === 0 && layer) await source.remove(scope, layer.version);
        else if (Object.keys(next).length > 0)
          await source.write(scope, next, layer?.version ?? null);
        if (request === sequence.current) await reload();
      } catch (error) {
        if (request === sequence.current) {
          // Never retain an optimistic value, stale permissions or another tenant's settings.
          reset(failure(error));
        }
      } finally {
        if (request === sequence.current) busy.current = false;
      }
    },
    [source, reload, reset],
  );

  const setSetting = useCallback(
    <K extends keyof UiSettings>(scope: EditableUiScope, key: K, value: UiSettings[K]) =>
      persist(scope, { ...(current.current.layers[scope]?.settings ?? {}), [key]: value }),
    [persist],
  );
  const clearSetting = useCallback(
    (scope: EditableUiScope, key: keyof UiSettings) => {
      const next = { ...(current.current.layers[scope]?.settings ?? {}) };
      delete next[key];
      return persist(scope, next);
    },
    [persist],
  );

  const value = useMemo<UiCustomizationValue>(
    () => ({
      settings: snapshot.settings,
      origin: snapshot.origin,
      layers: {
        user: snapshot.layers.user?.settings ?? null,
        tenant: snapshot.layers.tenant?.settings ?? null,
      },
      ready: status === 'ready',
      status,
      reload,
      canManage: (scope) => status === 'ready' && snapshot.allowed[scope],
      setSetting,
      clearSetting,
    }),
    [snapshot, status, reload, setSetting, clearSetting],
  );
  return (
    <UiCustomizationContext.Provider value={value}>{children}</UiCustomizationContext.Provider>
  );
}
