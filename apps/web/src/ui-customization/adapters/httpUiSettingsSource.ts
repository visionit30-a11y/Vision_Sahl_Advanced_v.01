import { authClient, AuthClient, HttpRequestError } from '../../auth/client';
import { UI_SETTING_KEYS, UI_SETTINGS_VALIDATORS } from '../contract/settings';
import type { EditableUiScope, UiSettings, UiSettingsPatch, UiScope } from '../contract/settings';
import type { UiSettingsOrigin } from '../resolution/resolveUiSettings';
import type { SettingsLayer, SettingsSnapshot, UiSettingsSource } from './UiSettingsSource';

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Invalid settings response.');
  return value as Record<string, unknown>;
}
function patch(value: unknown, complete = false): UiSettingsPatch {
  const record = object(value);
  if (
    Object.keys(record).some((key) => !UI_SETTING_KEYS.includes(key as keyof UiSettings)) ||
    UI_SETTING_KEYS.some(
      (key) => (complete || key in record) && !UI_SETTINGS_VALIDATORS[key](record[key]),
    )
  ) {
    throw new Error('Invalid settings response.');
  }
  return record as UiSettingsPatch;
}
function version(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 1)
    throw new Error('Invalid settings version.');
  return value as number;
}

/** Small HTTP adapter; uses only the existing cookie/CSRF transport. */
export function createHttpUiSettingsSource(client: AuthClient = authClient): UiSettingsSource {
  async function layer(
    scope: EditableUiScope,
  ): Promise<{ allowed: boolean; layer: SettingsLayer | null }> {
    try {
      const data = object(await (await client.request('/ui-settings/' + scope)).json());
      return {
        allowed: true,
        layer: { settings: patch(data.settings), version: version(data.version) },
      };
    } catch (error) {
      if (error instanceof HttpRequestError && error.status === 403)
        return { allowed: false, layer: null };
      if (error instanceof HttpRequestError && error.status === 404)
        return { allowed: true, layer: null };
      throw error;
    }
  }
  return {
    subscribe: (listener) => client.subscribe(listener),
    async load(): Promise<SettingsSnapshot> {
      // Establish the server-selected membership before any later unsafe operation.
      await client.me();
      await client.bootstrapCsrf();
      const [response, user, tenant] = await Promise.all([
        client.request('/ui-settings/effective'),
        layer('user'),
        layer('tenant'),
      ]);
      const effective = object(await response.json());
      const settings = patch(effective.settings, true) as UiSettings;
      const rawOrigins = object(effective.origins);
      const origin = {} as UiSettingsOrigin;
      for (const key of UI_SETTING_KEYS) {
        const value = rawOrigins[key];
        if (!['built-in', 'platform', 'tenant', 'user'].includes(value as string))
          throw new Error('Invalid settings origin.');
        origin[key] = value === 'built-in' ? 'builtIn' : (value as UiScope);
      }
      // Reject a mixed read when a layer changed between HTTP requests.
      for (const scope of ['user', 'tenant'] as const) {
        const data = scope === 'user' ? user : tenant;
        if (data.allowed && effective[scope + '_version'] !== (data.layer?.version ?? null)) {
          throw new HttpRequestError(409);
        }
      }
      return {
        settings,
        origin,
        layers: { user: user.layer, tenant: tenant.layer },
        allowed: { user: user.allowed, tenant: tenant.allowed },
      };
    },
    async write(scope, settings, expected_version) {
      await client.request('/ui-settings/' + scope, {
        method: 'PUT',
        body: JSON.stringify({ settings, expected_version }),
      });
    },
    async remove(scope, expectedVersion) {
      await client.request('/ui-settings/' + scope + '?expected_version=' + expectedVersion, {
        method: 'DELETE',
      });
    },
  };
}
export const httpUiSettingsSource = createHttpUiSettingsSource();
