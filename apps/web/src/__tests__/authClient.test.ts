import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  AuthClient,
  CsrfUnavailableError,
  SessionInvalidError,
  TenantContextChangedError,
} from '../auth/client';

afterEach(() => vi.restoreAllMocks());

function reply(body: unknown = {}, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), { status: 200, ...init });
}

describe('AuthClient', () => {
  it('uses cookie credentials and no-store without exposing a bearer', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(reply({ id: 'u', selectedMembershipId: null }));
    const client = new AuthClient({ fetcher });
    await client.me();
    const [, init] = fetcher.mock.calls[0] ?? [];
    expect(init).toMatchObject({ credentials: 'include', cache: 'no-store' });
    expect(new Headers(init?.headers).has('Authorization')).toBe(false);
  });

  it('keeps CSRF in memory and sends it only for unsafe methods', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(reply({}, { headers: { 'X-CSRF-Token': 'memory-token' } }))
      .mockResolvedValueOnce(reply());
    const client = new AuthClient({ fetcher });
    await client.bootstrapCsrf();
    await client.request('/unsafe', { method: 'POST' });
    expect(new Headers(fetcher.mock.calls[1]?.[1]?.headers).get('X-CSRF-Token')).toBe(
      'memory-token',
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('rejects unsafe requests before CSRF bootstrap', async () => {
    const client = new AuthClient({ fetcher: vi.fn() });
    await expect(client.request('/unsafe', { method: 'POST' })).rejects.toBeInstanceOf(
      CsrfUnavailableError,
    );
  });

  it('clears trusted state for invalid sessions and changed tenant context', async () => {
    const unauthorized = new AuthClient({
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 401 })),
    });
    await expect(unauthorized.me()).rejects.toBeInstanceOf(SessionInvalidError);

    const changed = new AuthClient({
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(
        new Response(null, {
          status: 409,
          headers: { 'X-Auth-Error': 'tenant_context_changed' },
        }),
      ),
    });
    await expect(changed.me()).rejects.toBeInstanceOf(TenantContextChangedError);
  });

  it('treats membership id as a selector and refreshes state after rotation', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(reply({}, { headers: { 'X-CSRF-Token': 'old' } }))
      .mockResolvedValueOnce(reply({}, { headers: { 'X-CSRF-Token': 'new' } }))
      .mockResolvedValueOnce(reply({ id: 'u', selectedMembershipId: 'm2' }))
      .mockResolvedValueOnce(reply());
    const client = new AuthClient({ fetcher });
    await client.bootstrapCsrf();
    const user = await client.switchTenant('m2');
    expect(user.selectedMembershipId).toBe('m2');
    expect(fetcher.mock.calls[2]?.[0]).toBe('/auth/me');
    expect(new Headers(fetcher.mock.calls[1]?.[1]?.headers).has('Authorization')).toBe(false);
    await client.request('/unsafe', { method: 'POST' });
    expect(new Headers(fetcher.mock.calls[3]?.[1]?.headers).get('X-CSRF-Token')).toBe('new');
  });
});

describe('AuthClient settings invalidation events', () => {
  it('notifies on authentication, rotation and logout without publishing secrets', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(reply({ id: 'u', selectedMembershipId: 'm1' }))
      .mockResolvedValueOnce(reply({}, { headers: { 'X-CSRF-Token': 'test-old' } }))
      .mockResolvedValueOnce(reply({}, { headers: { 'X-CSRF-Token': 'test-new' } }))
      .mockResolvedValueOnce(reply({ id: 'u', selectedMembershipId: 'm2' }))
      .mockResolvedValueOnce(reply());
    const client = new AuthClient({ fetcher });
    const listener = vi.fn();
    const unsubscribe = client.subscribe(listener);
    await client.me();
    await client.bootstrapCsrf();
    await client.switchTenant('m2');
    await client.logout();
    expect(listener.mock.calls.flat()).toContain('changed');
    expect(listener.mock.calls.at(-1)).toEqual(['invalid']);
    expect(
      listener.mock.calls.flat().every((value) => value === 'changed' || value === 'invalid'),
    ).toBe(true);
    unsubscribe();
    client.close();
  });

  it('discards a late response from before the session changed', async () => {
    let finish!: (response: Response) => void;
    const fetcher = vi
      .fn<typeof fetch>()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValueOnce(reply(null, { status: 401 }));
    const client = new AuthClient({ fetcher });
    const pending = client.request('/ui-settings/effective');
    await expect(client.me()).rejects.toBeInstanceOf(SessionInvalidError);
    finish(reply({ settings: { theme: 'sand-warm' } }));
    await expect(pending).rejects.toBeInstanceOf(TenantContextChangedError);
    client.close();
  });
});

it('bootstraps preauth before password login and uses rotated session CSRF', async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(reply({}, { headers: { 'X-CSRF-Token': 'preauth' } }))
    .mockResolvedValueOnce(reply({}, { headers: { 'X-CSRF-Token': 'session-csrf' } }))
    .mockResolvedValueOnce(reply({ id: 'u', selectedMembershipId: null }))
    .mockResolvedValueOnce(reply());
  const client = new AuthClient({ fetcher });
  await client.login('test@example.test', 'test password input');
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
    '/auth/preauth',
    '/auth/login',
    '/auth/me',
  ]);
  expect(new Headers(fetcher.mock.calls[1]?.[1]?.headers).get('X-CSRF-Token')).toBe('preauth');
  await client.request('/auth/logout', { method: 'POST' });
  expect(new Headers(fetcher.mock.calls[3]?.[1]?.headers).get('X-CSRF-Token')).toBe('session-csrf');
  expect(localStorage.length + sessionStorage.length).toBe(0);
  client.close();
});
