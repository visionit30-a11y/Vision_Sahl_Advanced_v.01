import { expect, test, type Page } from '@playwright/test';

async function client(page: Page): Promise<void> {
  await page.goto('/');
  await page.evaluate(async () => {
    const modulePath = '/src/auth/client.ts';
    const { AuthClient } = await import(modulePath);
    Object.assign(window, { authClient: new AuthClient() });
  });
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.request.get('/auth/test/session');
  await client(page);
});

test('cookie flags and browser storage keep the bearer inaccessible', async ({ page, context }) => {
  const consoleMessages: string[] = [];
  page.on('console', (message) => consoleMessages.push(message.text()));
  const response = await page.request.get('/auth/test/session');
  const setCookie = response.headers()['set-cookie'] ?? '';
  expect(setCookie).toContain('__Host-sahl_session=');
  expect(setCookie).toContain('Secure');
  expect(setCookie).toContain('HttpOnly');
  expect(setCookie).toContain('SameSite=Lax');
  expect(setCookie).toContain('Path=/');
  expect(setCookie).not.toMatch(/;\s*Domain=/i);

  const [cookie] = await context.cookies();
  expect(cookie).toMatchObject({
    name: '__Host-sahl_session',
    secure: true,
    httpOnly: true,
    sameSite: 'Lax',
    path: '/',
  });
  const storage = await page.evaluate(async () => ({
    local: { ...localStorage },
    session: { ...sessionStorage },
    indexedDb: (await indexedDB.databases()).map((item) => item.name),
    documentCookie: document.cookie,
  }));
  expect(storage).toEqual({ local: {}, session: {}, indexedDb: [], documentCookie: '' });
  await page.evaluate(async () => {
    await window.authClient.bootstrapCsrf();
  });
  expect(consoleMessages.join(' ')).not.toMatch(/sahl_session|csrf|bearer/i);
});

test('CSRF and Origin gates reject missing invalid foreign and stale tokens', async ({ page }) => {
  const oldCsrf = await page.evaluate(async () => {
    const response = await fetch('/auth/csrf', { credentials: 'include', cache: 'no-store' });
    return response.headers.get('X-CSRF-Token');
  });
  expect((await page.request.post('/auth/test/unsafe')).status()).toBe(403);
  expect(
    (
      await page.request.post('/auth/test/unsafe', {
        headers: { 'X-CSRF-Token': 'invalid', Origin: 'http://127.0.0.1:5173' },
      })
    ).status(),
  ).toBe(403);
  expect(
    (
      await page.request.post('/auth/test/unsafe', {
        headers: { 'X-CSRF-Token': oldCsrf ?? '', Origin: 'https://foreign.example' },
      })
    ).status(),
  ).toBe(403);
  await page.evaluate(async () => {
    await window.authClient.bootstrapCsrf();
  });
  expect(
    await page.evaluate(
      async () => (await window.authClient.request('/auth/test/unsafe', { method: 'POST' })).status,
    ),
  ).toBe(200);
  await page.evaluate(async () => {
    await window.authClient.switchTenant('membership-2');
  });
  expect(
    (
      await page.request.post('/auth/test/unsafe', {
        headers: { 'X-CSRF-Token': oldCsrf ?? '', Origin: 'http://127.0.0.1:5173' },
      })
    ).status(),
  ).toBe(403);
});

test('tenant rotation rejects stale tabs and ignores a forged tenant header', async ({
  page,
  context,
}) => {
  const stale = await context.newPage();
  await client(stale);
  await page.evaluate(async () => {
    await window.authClient.bootstrapCsrf();
    await window.authClient.me();
  });
  await stale.evaluate(async () => {
    await window.authClient.bootstrapCsrf();
    await window.authClient.me();
  });
  await page.evaluate(async () => {
    await window.authClient.switchTenant('membership-2');
  });
  await expect(
    stale.evaluate(async () => window.authClient.request('/auth/test/unsafe', { method: 'POST' })),
  ).rejects.toThrow(/CSRF bootstrap is required/i);
  const refreshedCsrf = await stale.evaluate(async () => {
    const response = await fetch('/auth/csrf', { credentials: 'include', cache: 'no-store' });
    return response.headers.get('X-CSRF-Token');
  });
  expect(
    await stale.evaluate(async (csrf) => {
      const response = await fetch('/auth/test/unsafe', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'X-CSRF-Token': csrf ?? '',
          'X-Expected-Membership-ID': 'membership-1',
        },
      });
      return response.status;
    }, refreshedCsrf),
  ).toBe(409);
  const membership = await page.evaluate(async () => {
    const response = await window.authClient.request('/auth/test/unsafe', {
      method: 'POST',
      headers: { 'X-Tenant-ID': 'forged' },
    });
    return (await response.json()).membership;
  });
  expect(membership).toBe('membership-2');
});

test('logout revokes the session clears the cookie and protects subsequent calls', async ({
  page,
  context,
}) => {
  await page.evaluate(async () => {
    await window.authClient.bootstrapCsrf();
    await window.authClient.logout();
  });
  expect(
    (await context.cookies()).find((cookie) => cookie.name === '__Host-sahl_session'),
  ).toBeUndefined();
  await expect(page.evaluate(async () => window.authClient.me())).rejects.toThrow(
    /session is no longer valid/i,
  );
});

declare global {
  interface Window {
    authClient: import('../../src/auth/client').AuthClient;
  }
}
