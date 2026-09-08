import { describe, expect, it, vi } from 'vitest';
import { AuthClient, HttpRequestError } from '../auth/client';
import { createHttpUiSettingsSource } from '../ui-customization/adapters/httpUiSettingsSource';
import { BUILT_IN_UI_SETTINGS, UI_SETTING_KEYS } from '../ui-customization/contract/settings';

const effective = {
  settings: BUILT_IN_UI_SETTINGS,
  origins: Object.fromEntries(UI_SETTING_KEYS.map((key) => [key, 'built-in'])),
  user_version: null,
  tenant_version: null,
  platform_version: null,
};
function setup(layerStatus = 404) {
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path === '/auth/me') return Response.json({ id: 'u', selectedMembershipId: 'm' });
    if (path === '/auth/csrf')
      return new Response(null, { headers: { 'X-CSRF-Token': 'test-memory' } });
    if (path === '/ui-settings/effective') return Response.json(effective);
    return new Response(null, { status: layerStatus });
  });
  const client = new AuthClient({ fetcher });
  return { client, fetcher, source: createHttpUiSettingsSource(client) };
}
describe('HTTP settings adapter', () => {
  it('loads effective and protected layers through existing auth with no identity selectors', async () => {
    const f = setup();
    const result = await f.source.load();
    expect(result.settings).toEqual(BUILT_IN_UI_SETTINGS);
    expect(result.origin.theme).toBe('builtIn');
    expect(result.allowed).toEqual({ user: true, tenant: true });
    for (const [, init] of f.fetcher.mock.calls)
      expect(init).toMatchObject({ credentials: 'include', cache: 'no-store' });
    expect(f.fetcher.mock.calls.map(([url]) => url)).toEqual([
      '/auth/me',
      '/auth/csrf',
      '/ui-settings/effective',
      '/ui-settings/user',
      '/ui-settings/tenant',
    ]);
    f.client.close();
  });
  it('does not offer writes after protected layer returns 403', async () => {
    const f = setup(403);
    expect((await f.source.load()).allowed).toEqual({ user: false, tenant: false });
    f.client.close();
  });
  it('sends CSRF and expected versions on PUT and DELETE without selectors', async () => {
    const f = setup();
    await f.source.load();
    f.fetcher.mockResolvedValue(new Response(null, { status: 204 }));
    await f.source.write('user', { theme: 'sand-warm' }, null);
    await f.source.remove('tenant', 3);
    expect(JSON.parse(String(f.fetcher.mock.calls[5]?.[1]?.body))).toEqual({
      settings: { theme: 'sand-warm' },
      expected_version: null,
    });
    expect(new Headers(f.fetcher.mock.calls[5]?.[1]?.headers).get('X-Expected-Membership-ID')).toBe(
      'm',
    );
    expect(new Headers(f.fetcher.mock.calls[5]?.[1]?.headers).get('X-CSRF-Token')).toBe(
      'test-memory',
    );
    expect(f.fetcher.mock.calls[6]?.[0]).toBe('/ui-settings/tenant?expected_version=3');
    f.client.close();
  });
  it('propagates conflicts with a structured status', async () => {
    const f = setup();
    await f.source.load();
    f.fetcher.mockResolvedValue(new Response(null, { status: 409 }));
    await expect(f.source.write('user', {}, 2)).rejects.toMatchObject({ status: 409 });
    f.client.close();
  });
  it('rejects mismatched effective/layer versions', async () => {
    const f = setup();
    const original = f.fetcher.getMockImplementation()!;
    f.fetcher.mockImplementation(async (url, init) =>
      String(url) === '/ui-settings/user'
        ? Response.json({ settings: {}, version: 4 })
        : original(url, init),
    );
    await expect(f.source.load()).rejects.toBeInstanceOf(HttpRequestError);
    f.client.close();
  });
  it('rejects invalid response values rather than silently falling back', async () => {
    const f = setup();
    const original = f.fetcher.getMockImplementation()!;
    f.fetcher.mockImplementation(async (url, init) =>
      String(url) === '/ui-settings/effective'
        ? Response.json({ ...effective, settings: { ...BUILT_IN_UI_SETTINGS, theme: 'invalid' } })
        : original(url, init),
    );
    await expect(f.source.load()).rejects.toThrow('Invalid settings response.');
    f.client.close();
  });
});
