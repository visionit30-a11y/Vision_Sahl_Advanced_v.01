import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { expect, test as base } from '@playwright/test';
import type { APIResponse, Page } from '@playwright/test';

type Account = Record<
  | 'user'
  | 'foreign_user'
  | 'tenant_a'
  | 'tenant_b'
  | 'tenant_c'
  | 'membership_a'
  | 'membership_b'
  | 'membership_c'
  | 'role_a'
  | 'role_b'
  | 'bearer'
  | 'email'
  | 'password',
  string
>;
const origin =
  process.env.SAHL_VERIFY_LOCAL_DEV === '1' ? 'http://localhost:5173' : 'http://localhost:5187';
const testSecrets = new Set<string>();
const CSRF_WINDOW_MS = 60_000;
const CSRF_SCENARIO_BUDGET = 20;
const CSRF_WINDOW_LIMIT = 30;
const CSRF_CLOCK_MARGIN = 2;
let csrfWindow = -1;
let csrfWindowRequests = 0;
let initialCsrfWindowAligned = false;

function currentCsrfWindow(): number {
  const current = Math.floor(Date.now() / CSRF_WINDOW_MS);
  if (current !== csrfWindow) {
    csrfWindow = current;
    csrfWindowRequests = 0;
  }
  return current;
}

async function reserveRealCsrfBudget(): Promise<void> {
  const current = currentCsrfWindow();
  if (
    !initialCsrfWindowAligned ||
    csrfWindowRequests + CSRF_SCENARIO_BUDGET + CSRF_CLOCK_MARGIN > CSRF_WINDOW_LIMIT
  ) {
    // PostgreSQL's existing limit uses epoch-aligned one-minute buckets. Honor
    // it instead of resetting counters, weakening the policy, or retrying 429.
    const readyAt = (current + 1) * CSRF_WINDOW_MS + 1000;
    while (Date.now() < readyAt) {
      await new Promise((resolve) => setTimeout(resolve, Math.min(1000, readyAt - Date.now())));
    }
    currentCsrfWindow();
  }
  initialCsrfWindowAligned = true;
}

function rememberSecret(value: string | undefined): void {
  if (value) testSecrets.add(value);
}

function rememberHeaders(headers: Record<string, string>): void {
  rememberSecret(headers['x-csrf-token']);
  for (const line of (headers['set-cookie'] ?? '').split('\n')) {
    const value = line.match(/^[^=;]+=(.*?)(?:;|$)/)?.[1];
    rememberSecret(value);
  }
}

// Playwright's transport errors may otherwise include Cookie/CSRF request headers.
async function protectedApi(request: () => Promise<APIResponse>): Promise<APIResponse> {
  try {
    const response = await request();
    rememberHeaders(response.headers());
    return response;
  } catch {
    throw new Error('Real API request failed before a response was available.');
  }
}

async function browserCsrf(page: Page): Promise<string> {
  const result = await page.evaluate(async () => {
    const response = await fetch('/auth/csrf', { credentials: 'include', cache: 'no-store' });
    return { status: response.status, token: response.headers.get('x-csrf-token') ?? '' };
  });
  expect(result.status).toBe(204);
  expect(Boolean(result.token)).toBe(true);
  rememberSecret(result.token);
  return result.token;
}

// Ephemeral fixture secrets use anonymous pipes only, never output/artifacts.
async function database(action: string, state?: Account): Promise<Account> {
  return new Promise((done, reject) => {
    const api = resolve(process.cwd(), '../api');
    const python = resolve(
      api,
      process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python',
    );
    const child = spawn(python, ['-m', 'tests.browser_fixture'], {
      cwd: api,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    let output = '';
    child.stdout.setEncoding('utf8').on('data', (chunk: string) => {
      output += chunk;
    });
    child.stderr.resume();
    child.once('error', () => reject(new Error('Real database fixture could not start.')));
    child.once('close', (code) => {
      if (code !== 0) return reject(new Error('Real database fixture failed.'));
      try {
        done(JSON.parse(output) as Account);
      } catch {
        reject(new Error('Real database fixture returned an invalid result.'));
      }
    });
    child.stdin.end(JSON.stringify({ action, state }));
  });
}

const test = base.extend<{ account: Account; safety: void }>({
  safety: [
    async ({ context }, runTest) => {
      testSecrets.clear();
      const messages: string[] = [];
      const captures: Promise<void>[] = [];
      let captureFailed = false;
      let scenarioCsrfRequests = 0;
      await reserveRealCsrfBudget();
      context.on('request', (request) => {
        if (request.method() === 'GET' && new URL(request.url()).pathname === '/auth/csrf') {
          currentCsrfWindow();
          csrfWindowRequests += 1;
          scenarioCsrfRequests += 1;
        }
      });
      context.on('console', (message) => messages.push(message.text()));
      context.on('page', (page) => {
        page.on('pageerror', (error) => messages.push(error.message));
      });
      context.on('response', (response) => {
        captures.push(
          response
            .allHeaders()
            .then(rememberHeaders)
            .catch(() => {
              captureFailed = true;
            }),
        );
      });
      await runTest();
      expect(scenarioCsrfRequests).toBeLessThanOrEqual(CSRF_SCENARIO_BUDGET);
      await Promise.all(captures);
      for (const cookie of await context.cookies()) rememberSecret(cookie.value);
      expect(captureFailed).toBe(false);
      expect(
        messages.some((line) => [...testSecrets].some((secret) => line.includes(secret))),
      ).toBe(false);
      for (const page of context.pages()) {
        if (page.isClosed() || !page.url().startsWith('http')) continue;
        expect(
          await page.evaluate(
            async () =>
              localStorage.length === 0 &&
              sessionStorage.length === 0 &&
              (await indexedDB.databases()).length === 0 &&
              document.cookie === '',
          ),
        ).toBe(true);
      }
    },
    { auto: true, timeout: 90_000 },
  ],
  account: async ({ context }, runTest) => {
    const state = await database('seed');
    rememberSecret(state.bearer);
    try {
      await context.addCookies([
        {
          name: '__Host-sahl_session',
          value: state.bearer,
          domain: 'localhost',
          path: '/',
          secure: true,
          httpOnly: true,
          sameSite: 'Lax',
        },
      ]);
      await runTest(state);
    } finally {
      await database('cleanup', state);
    }
  },
});

test('real FastAPI contract and unauthenticated no-store denial', async ({ page }) => {
  const response = await protectedApi(() => page.request.get('http://127.0.0.1:8010/openapi.json'));
  expect(response.ok()).toBe(true);
  const schema = (await response.json()) as { paths: Record<string, Record<string, unknown>> };
  for (const [path, method] of [
    ['/auth/me', 'get'],
    ['/auth/memberships', 'get'],
    ['/auth/csrf', 'get'],
    ['/auth/tenant/switch', 'post'],
    ['/auth/logout', 'post'],
    ['/ui-settings/effective', 'get'],
  ] as const)
    expect(Boolean(schema.paths[path]?.[method])).toBe(true);
  await page.goto('/design-system');
  const proof = await page.evaluate(async () => {
    const health = await fetch('/health/db');
    const response = await fetch('/ui-settings/effective', {
      credentials: 'include',
      cache: 'no-store',
    });
    return { db: health.ok, status: response.status, cache: response.headers.get('cache-control') };
  });
  expect(proof).toEqual({ db: true, status: 401, cache: 'no-store' });
  await expect(page.getByText('سجّل الدخول لتحميل الإعدادات')).toBeVisible();
});

test('real patches survive refresh and deletion restores inheritance origins', async ({
  page,
  account,
}) => {
  expect(Boolean(account.user)).toBe(true);
  await page.goto('/design-system');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'navy-institutional');
  await expect(page.locator('input[value="sand-warm"]')).toBeEnabled();
  await page.locator('input[value="sand-warm"]').check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'sand-warm');
  const effective = page.waitForResponse((response) =>
    response.url().endsWith('/ui-settings/effective'),
  );
  await page.reload();
  expect((await effective).status()).toBe(200);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'sand-warm');
  expect(
    await page.evaluate(
      async () => (await (await fetch('/ui-settings/effective')).json()).origins.theme as string,
    ),
  ).toBe('user');
  await page.getByRole('button', { name: 'العودة إلى الموروث' }).first().click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'navy-institutional');
  expect(
    await page.evaluate(
      async () => (await (await fetch('/ui-settings/effective')).json()).origins.theme as string,
    ),
  ).toBe('tenant');
  await page.locator('input[value="tenant"]').check();
  await page.locator('input[value="slate-neutral"]').check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'slate-neutral');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'slate-neutral');
});

test('real rotation refreshes tabs and rejects old bearer CSRF and membership', async ({
  page,
  context,
  account,
}) => {
  await page.goto('/design-system');
  await expect(page.locator('input[value="sand-warm"]')).toBeEnabled();
  const other = await context.newPage();
  await other.goto('/design-system');
  await expect(other.locator('input[value="sand-warm"]')).toBeEnabled();
  const oldCsrf = await browserCsrf(page);
  const before = (await context.cookies()).find(
    (item) => item.name === '__Host-sahl_session',
  )?.value;
  const switchResponse = page.waitForResponse((response) =>
    response.url().endsWith('/auth/tenant/switch'),
  );
  await page.evaluate(async (membership) => {
    const path = '/src/auth/client.ts';
    const { authClient } = await import(path);
    await authClient.switchTenant(membership);
  }, account.membership_b);
  const switched = await switchResponse;
  expect(switched.status()).toBe(204);
  const setCookie = (await switched.headerValue('set-cookie')) ?? '';
  expect(
    ['__Host-sahl_session=', 'Secure', 'HttpOnly', 'SameSite=lax', 'Path=/'].every((part) =>
      setCookie.toLowerCase().includes(part.toLowerCase()),
    ),
  ).toBe(true);
  expect(/;\s*Domain=/i.test(setCookie)).toBe(false);
  const cookie = (await context.cookies()).find((item) => item.name === '__Host-sahl_session');
  expect(
    Boolean(
      cookie &&
      cookie.value !== before &&
      cookie.secure &&
      cookie.httpOnly &&
      cookie.sameSite === 'Lax' &&
      cookie.path === '/',
    ),
  ).toBe(true);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'green-institutional');
  await expect(other.locator('html')).toHaveAttribute('data-theme', 'green-institutional');
  expect(
    (
      await protectedApi(() =>
        page.request.get('http://127.0.0.1:8010/auth/me', {
          headers: { Cookie: '__Host-sahl_session=' + before },
        }),
      )
    ).status(),
  ).toBe(401);
  expect(
    (
      await protectedApi(() =>
        page.request.put('/ui-settings/user', {
          headers: {
            Origin: origin,
            'X-CSRF-Token': oldCsrf,
            'X-Expected-Membership-ID': account.membership_b,
          },
          data: { settings: { theme: 'sand-warm' }, expected_version: null },
        }),
      )
    ).status(),
  ).toBe(403);
  const csrf = await browserCsrf(page);
  const stale = await other.evaluate(
    async ({ csrf, membership }) => {
      const response = await fetch('/ui-settings/user', {
        method: 'PUT',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrf,
          'X-Expected-Membership-ID': membership,
        },
        body: JSON.stringify({ settings: { theme: 'sand-warm' }, expected_version: null }),
      });
      return { status: response.status, code: response.headers.get('X-Auth-Error') };
    },
    { csrf, membership: account.membership_a },
  );
  expect(stale).toEqual({ status: 409, code: 'tenant_context_changed' });
  expect(
    await page.evaluate(async (foreign) => {
      const response = await fetch('/auth/me', { headers: { 'X-Tenant-ID': foreign } });
      return (await response.json()).selectedMembershipId as string;
    }, account.tenant_c),
  ).toBe(account.membership_b);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'green-institutional');
});

test('real CSRF Origin and foreign membership gates fail closed', async ({
  page,
  context,
  account,
}) => {
  await page.goto('/design-system');
  await expect(page.locator('input[value="sand-warm"]')).toBeEnabled();
  const csrf = await browserCsrf(page);
  const data = { settings: { theme: 'sand-warm' }, expected_version: null };
  const deniedHeaders: Record<string, string>[] = [
    { Origin: origin, 'X-Expected-Membership-ID': account.membership_a },
    { Origin: origin, 'X-CSRF-Token': 'invalid', 'X-Expected-Membership-ID': account.membership_a },
    {
      Origin: 'https://foreign.example',
      'X-CSRF-Token': csrf,
      'X-Expected-Membership-ID': account.membership_a,
    },
  ];
  for (const headers of deniedHeaders)
    expect(
      (await protectedApi(() => page.request.put('/ui-settings/user', { headers, data }))).status(),
    ).toBe(403);
  expect(
    (
      await protectedApi(() =>
        page.request.post('/auth/tenant/switch', {
          headers: {
            Origin: origin,
            'X-CSRF-Token': csrf,
            'X-Expected-Membership-ID': account.membership_a,
          },
          data: { membership_id: account.membership_c },
        }),
      )
    ).status(),
  ).toBe(403);
  const foreign = await context.newPage();
  await foreign.goto('http://127.0.0.1:8010/health');
  expect(
    await foreign.evaluate(
      async ({ csrf, membership, target }) => {
        try {
          await fetch(`${target}/ui-settings/user`, {
            method: 'PUT',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRF-Token': csrf,
              'X-Expected-Membership-ID': membership,
            },
            body: JSON.stringify({ settings: { theme: 'sand-warm' }, expected_version: null }),
          });
          return false;
        } catch (error) {
          return error instanceof TypeError;
        }
      },
      { csrf, membership: account.membership_a, target: origin },
    ),
  ).toBe(true);
  expect(
    await page.evaluate(async () => {
      const response = await fetch('/ui-settings/effective', { credentials: 'include' });
      return (await response.json()).settings.theme as string;
    }),
  ).toBe('navy-institutional');
  expect(
    await page.evaluate(async () => {
      const path = '/src/auth/client.ts';
      const { authClient } = await import(path);
      return (
        await authClient.request('/ui-settings/user', {
          method: 'PUT',
          body: JSON.stringify({ settings: { theme: 'sand-warm' }, expected_version: null }),
        })
      ).status;
    }),
  ).toBe(200);
});

test('real 409 blocks stale writes and logout clears cookie and settings', async ({
  page,
  context,
  account,
}) => {
  expect(Boolean(account.user)).toBe(true);
  await page.goto('/design-system');
  await expect(page.locator('input[value="sand-warm"]')).toBeEnabled();
  await page.evaluate(async () => {
    const path = '/src/auth/client.ts';
    const { authClient } = await import(path);
    await authClient.request('/ui-settings/tenant', {
      method: 'PUT',
      body: JSON.stringify({ settings: { theme: 'slate-neutral' }, expected_version: 1 }),
    });
  });
  await page.locator('input[value="tenant"]').check();
  await page.locator('input[value="sand-warm"]').click();
  await expect(page.getByText('تغيرت الإعدادات. أعد جلبها قبل المحاولة مجددًا.')).toBeVisible();
  await expect(page.locator('input[value="sand-warm"]')).toHaveCount(0);
  await page.getByRole('button', { name: 'إعادة جلب الإعدادات' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'slate-neutral');
  await page.evaluate(async () => {
    const path = '/src/auth/client.ts';
    const { authClient } = await import(path);
    await authClient.logout();
  });
  expect((await context.cookies()).some((cookie) => cookie.name === '__Host-sahl_session')).toBe(
    false,
  );
  await expect(page.getByText('سجّل الدخول لتحميل الإعدادات')).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'teal-calm');
  expect((await protectedApi(() => page.request.get('/ui-settings/effective'))).status()).toBe(401);
});

test('real 403 disables tenant writes and storage console expose no secrets', async ({
  page,
  context,
  account,
}) => {
  await database('deny_tenant', account);
  await page.goto('/design-system');
  await expect(page.locator('input[value="sand-warm"]')).toBeEnabled();
  await page.locator('input[value="tenant"]').check();
  await expect(page.getByText('طبقة الصلاحيات لا تسمح بتعديل هذا النطاق.')).toBeVisible();
  await expect(page.locator('input[value="sand-warm"]')).toHaveCount(0);
  await expect(page.locator('input[value="platform"]')).toHaveCount(0);
  await expect(page.locator('[value="preview-tenant"]')).toHaveCount(0);
  await page.locator('input[value="user"]').check();
  await page.locator('input[value="sand-warm"]').check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'sand-warm');
  for (const cookie of await context.cookies()) rememberSecret(cookie.value);
  expect(
    await page.evaluate(
      async () =>
        localStorage.length === 0 &&
        sessionStorage.length === 0 &&
        (await indexedDB.databases()).length === 0 &&
        document.cookie === '',
    ),
  ).toBe(true);
});

test('real backend wins over legacy storage and network failure stays visible', async ({
  page,
  account,
}) => {
  expect(Boolean(account.user)).toBe(true);
  await page.goto('/design-system');
  await expect(page.locator('input[value="sand-warm"]')).toBeEnabled();
  // Exact keys from the removed Phase 1 browser adapter, not a new storage contract.
  await page.evaluate(() => {
    localStorage.setItem('sahl.ui.platform', JSON.stringify({ theme: 'sand-warm' }));
    localStorage.setItem('sahl.ui.tenant.preview-tenant', JSON.stringify({ theme: 'sand-warm' }));
  });
  try {
    await page.reload();
    await expect(page.locator('input[value="sand-warm"]')).toBeEnabled();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'navy-institutional');
    await page.route('**/ui-settings/effective', (route) => route.abort('connectionfailed'));
    await page.reload();
    await expect(
      page.getByText('تعذر تحميل الإعدادات أو حفظها. تحقق من الاتصال وأعد المحاولة.'),
    ).toBeVisible();
    await expect(
      page.getByText('الإعدادات المعروضة مؤقتة؛ لم يتم تأكيد الإعدادات الفعلية المحفوظة.'),
    ).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'teal-calm');
    await expect(page.locator('input[value="sand-warm"]')).toHaveCount(0);
    await page.unroute('**/ui-settings/effective');
    await page.getByRole('button', { name: 'إعادة جلب الإعدادات' }).click();
    await expect(page.locator('input[value="sand-warm"]')).toBeEnabled();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'navy-institutional');
  } finally {
    await page.unroute('**/ui-settings/effective');
    await page.evaluate(() => {
      localStorage.removeItem('sahl.ui.platform');
      localStorage.removeItem('sahl.ui.tenant.preview-tenant');
    });
  }
});

test('real login form establishes a fresh PostgreSQL session and selected tenant', async ({
  page,
  context,
}) => {
  const account = await database('seed_login');
  rememberSecret(account.password);
  try {
    expect((await context.cookies()).length).toBe(0);
    await page.goto('/login');
    await page.locator('input[name="email"]').fill(account.email);
    await page.locator('input[name="password"]').fill(account.password);
    const loginResponse = page.waitForResponse((response) =>
      response.url().endsWith('/auth/login'),
    );
    await page.locator('button[type="submit"]').click();
    const loginHeaders = await (await loginResponse).allHeaders();
    const cookieHeader = loginHeaders['set-cookie'] ?? '';
    expect(
      cookieHeader.includes('__Host-sahl_session=') &&
        /HttpOnly/i.test(cookieHeader) &&
        /Secure/i.test(cookieHeader) &&
        /SameSite=Lax/i.test(cookieHeader) &&
        /Path=\//i.test(cookieHeader) &&
        !/Domain=/i.test(cookieHeader),
    ).toBe(true);
    await expect(page.getByRole('button', { name: 'A', exact: true })).toBeVisible();
    const cookies = await context.cookies();
    const cookie = cookies.find((item) => item.name === '__Host-sahl_session');
    expect(Boolean(cookie)).toBe(true);
    expect(
      cookie?.secure && cookie.httpOnly && cookie.sameSite === 'Lax' && cookie.path === '/',
    ).toBe(true);
    await page.getByRole('button', { name: 'A', exact: true }).click();
    await expect
      .poll(async () =>
        page.evaluate(async () => {
          const me = await fetch('/auth/me', { cache: 'no-store' });
          const data = await me.json();
          return Boolean(data.selectedMembershipId);
        }),
      )
      .toBe(true);
    const proof = await page.evaluate(async () => {
      const response = await fetch('/ui-settings/effective', { cache: 'no-store' });
      return response.status;
    });
    expect(proof).toBe(200);
    await page.reload();
    expect((await protectedApi(() => page.request.get('/auth/me'))).status()).toBe(200);
    await expect(page.getByRole('button', { name: 'B', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'B', exact: true }).click();
    await expect
      .poll(async () =>
        page.evaluate(async () => {
          const response = await fetch('/ui-settings/effective', { cache: 'no-store' });
          return (await response.json()).settings?.theme;
        }),
      )
      .toBe('green-institutional');
    await page.evaluate(async () => {
      const path = '/src/auth/client.ts';
      const { authClient } = await import(path);
      await authClient.me();
      await authClient.bootstrapCsrf();
      await authClient.request('/ui-settings/user', {
        method: 'PUT',
        body: JSON.stringify({ settings: { theme: 'sand-warm' }, expected_version: null }),
      });
      await authClient.logout();
    });
    expect((await protectedApi(() => page.request.get('/auth/me'))).status()).toBe(401);
    expect((await context.cookies()).some((item) => item.name === '__Host-sahl_session')).toBe(
      false,
    );
  } finally {
    await database('cleanup', account);
  }
});
