import { spawn, spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test as base } from '@playwright/test';
import type { APIResponse, BrowserContext, Page } from '@playwright/test';

type Account = Record<
  | 'user'
  | 'foreign_user'
  | 'approver_user'
  | 'tenant_a'
  | 'tenant_b'
  | 'tenant_c'
  | 'membership_a'
  | 'membership_b'
  | 'membership_c'
  | 'approver_membership'
  | 'role_a'
  | 'role_b'
  | 'role_approver'
  | 'bearer'
  | 'email'
  | 'approver_email'
  | 'approver_password'
  | 'invite_email'
  | 'password',
  string
>;
const origin =
  process.env.SAHL_VERIFY_LOCAL_DEV === '1' ? 'http://localhost:5173' : 'http://localhost:5187';
const testSecrets = new Set<string>();
const CSRF_WINDOW_MS = 60_000;
// The application shell and permission provider each prove their server state.
// Reserve their two bootstrap reads while staying below the backend limit.
const CSRF_SCENARIO_BUDGET = 22;
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

async function waitForFreshCsrfWindow(current = currentCsrfWindow()): Promise<void> {
  const readyAt = (current + 1) * CSRF_WINDOW_MS + 1000;
  while (Date.now() < readyAt) {
    await new Promise((resolve) => setTimeout(resolve, Math.min(1000, readyAt - Date.now())));
  }
  currentCsrfWindow();
  initialCsrfWindowAligned = true;
}

async function reserveRealCsrfBudget(): Promise<void> {
  const current = currentCsrfWindow();
  if (
    !initialCsrfWindowAligned ||
    csrfWindowRequests + CSRF_SCENARIO_BUDGET + CSRF_CLOCK_MARGIN > CSRF_WINDOW_LIMIT
  ) {
    // PostgreSQL's existing limit uses epoch-aligned one-minute buckets. Honor
    // it instead of resetting counters, weakening the policy, or retrying 429.
    await waitForFreshCsrfWindow(current);
  }
  initialCsrfWindowAligned = true;
}

function trackRealCsrfBudget(context: BrowserContext): void {
  context.on('request', (request) => {
    if (request.method() === 'GET' && new URL(request.url()).pathname === '/auth/csrf') {
      currentCsrfWindow();
      csrfWindowRequests += 1;
    }
  });
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

async function loginAndSelectTenant(page: Page, email: string, password: string): Promise<void> {
  rememberSecret(password);
  await page.goto('/login');
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole('button', { name: 'A', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'A', exact: true }).click();
  await expect(page).toHaveURL('/');
  await expect
    .poll(async () =>
      page.evaluate(async () => {
        const response = await fetch('/auth/me', { credentials: 'include', cache: 'no-store' });
        if (!response.ok) return false;
        return Boolean(
          ((await response.json()) as { selectedMembershipId?: string | null })
            .selectedMembershipId,
        );
      }),
    )
    .toBe(true);
}

type PythonLauncher = { command: string; args: string[]; probeArgs: string[] };

const databaseEnvironmentKeys = ['DATABASE_URL', 'MIGRATION_DATABASE_URL'] as const;

function fixtureDatabaseEnvironment(apiDirectory: string): NodeJS.ProcessEnv {
  const values: NodeJS.ProcessEnv = {};
  for (const key of databaseEnvironmentKeys) {
    if (process.env[key]) values[key] = process.env[key];
  }

  const candidates = [
    resolve(apiDirectory, '..', '..', '.env'),
    resolve(apiDirectory, '..', '..', '..', '.env'),
  ];
  for (const candidate of candidates) {
    if (!existsSync(candidate)) continue;
    for (const line of readFileSync(candidate, 'utf8').split(/\r?\n/u)) {
      const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/u);
      if (
        !match ||
        !databaseEnvironmentKeys.includes(match[1] as (typeof databaseEnvironmentKeys)[number])
      ) {
        continue;
      }
      const key = match[1] as (typeof databaseEnvironmentKeys)[number];
      if (values[key]) continue;
      const raw = match[2] ?? '';
      values[key] =
        (raw.startsWith('"') && raw.endsWith('"')) || (raw.startsWith("'") && raw.endsWith("'"))
          ? raw.slice(1, -1)
          : raw;
    }
  }
  return values;
}

function resolveFixtureLauncher(apiDirectory: string): PythonLauncher {
  const pythonProbe = ['-c', 'import argon2, psycopg, sqlalchemy'];
  if (process.env.BROWSER_FIXTURE_PYTHON) {
    const configured = {
      command: resolve(apiDirectory, process.env.BROWSER_FIXTURE_PYTHON),
      args: ['-m', 'tests.browser_fixture'],
      probeArgs: pythonProbe,
    };
    if (fixtureLauncherIsReady(configured, apiDirectory)) return configured;
    throw new Error('Configured browser fixture Python lacks required dependencies.');
  }

  const candidates: PythonLauncher[] = [
    {
      command: resolve(apiDirectory, '.venv', 'Scripts', 'python.exe'),
      args: ['-m', 'tests.browser_fixture'],
      probeArgs: pythonProbe,
    },
    {
      command: resolve(apiDirectory, '.venv', 'bin', 'python'),
      args: ['-m', 'tests.browser_fixture'],
      probeArgs: pythonProbe,
    },
    {
      command: resolve(
        apiDirectory,
        '..',
        '..',
        '..',
        'apps',
        'api',
        '.venv',
        'Scripts',
        'python.exe',
      ),
      args: ['-m', 'tests.browser_fixture'],
      probeArgs: pythonProbe,
    },
    {
      command: resolve(apiDirectory, '..', '..', '..', 'apps', 'api', '.venv', 'bin', 'python'),
      args: ['-m', 'tests.browser_fixture'],
      probeArgs: pythonProbe,
    },
    {
      command: 'uv',
      args: ['run', '--frozen', '--no-sync', 'python', '-m', 'tests.browser_fixture'],
      probeArgs: ['run', '--frozen', '--no-sync', 'python', ...pythonProbe],
    },
    { command: 'python', args: ['-m', 'tests.browser_fixture'], probeArgs: pythonProbe },
    { command: 'python3', args: ['-m', 'tests.browser_fixture'], probeArgs: pythonProbe },
  ];

  for (const candidate of candidates) {
    if (fixtureLauncherIsReady(candidate, apiDirectory)) return candidate;
  }

  throw new Error('No browser fixture Python with required dependencies is available.');
}

function fixtureLauncherIsReady(launcher: PythonLauncher, apiDirectory: string): boolean {
  if (!['uv', 'python', 'python3'].includes(launcher.command) && !existsSync(launcher.command)) {
    return false;
  }
  const result = spawnSync(launcher.command, launcher.probeArgs, {
    cwd: apiDirectory,
    env: { ...process.env, ...fixtureDatabaseEnvironment(apiDirectory) },
    stdio: 'ignore',
    windowsHide: true,
    timeout: 10_000,
  });
  return result.status === 0;
}

// Ephemeral fixture secrets use anonymous pipes only, never output/artifacts.
async function database(action: string, state?: Account): Promise<Account> {
  return new Promise((done, reject) => {
    const api = resolve(process.cwd(), '../api');
    const launcher = resolveFixtureLauncher(api);
    const child = spawn(launcher.command, launcher.args, {
      cwd: api,
      env: { ...process.env, ...fixtureDatabaseEnvironment(api) },
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

// The real suite deliberately waits for PostgreSQL-backed, epoch-aligned
// throttle windows instead of resetting counters. Keep that wait inside the
// test contract on slower CI runners.
test.describe.configure({ timeout: 120_000 });

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
  await expect(page.getByRole('heading', { name: 'تسجيل الدخول' })).toBeVisible();
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
  const logoutResponse = page.waitForResponse((response) =>
    response.url().endsWith('/auth/logout'),
  );
  await page.getByRole('button', { name: 'تسجيل الخروج' }).click();
  expect((await logoutResponse).status()).toBe(204);
  expect((await context.cookies()).some((cookie) => cookie.name === '__Host-sahl_session')).toBe(
    false,
  );
  await expect(page.getByRole('heading', { name: 'تسجيل الدخول' })).toBeVisible();
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

test('real shell uses server permissions and preserves direction across viewports', async ({
  page,
  account,
}) => {
  expect(Boolean(account.user)).toBe(true);
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.getByRole('navigation', { name: 'التنقل الرئيسي' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'نظام التصميم' })).toBeVisible();
  await expect(page.getByText('A', { exact: true }).first()).toBeVisible();

  await page.getByRole('button', { name: 'تغيير اللغة' }).click();
  await page.getByRole('menuitem', { name: 'English' }).click();
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
  await expect(page.getByRole('heading', { name: 'Sahl Developer Platform' })).toBeVisible();

  for (const viewport of [
    { width: 768, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await expect(page.getByRole('heading', { name: 'Sahl Developer Platform' })).toBeVisible();
  }

  await page.evaluate(() => localStorage.removeItem('sahl.language'));
});

test('real shell hides denied navigation and rejects a direct protected URL', async ({
  page,
  account,
}) => {
  await database('deny_user', account);
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'نظام التصميم' })).toHaveCount(0);
  await page.goto('/design-system');
  await expect(page.getByRole('heading', { name: 'غير مصرح' })).toBeVisible();
  expect((await protectedApi(() => page.request.get('/ui-settings/effective'))).status()).toBe(403);
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

test('real workflow request returns, resubmits, approves, and preserves history', async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const account = await database('seed_login');
  const requesterContext = await browser.newContext({ baseURL: origin });
  const approverContext = await browser.newContext({ baseURL: origin });
  trackRealCsrfBudget(requesterContext);
  trackRealCsrfBudget(approverContext);
  const requester = await requesterContext.newPage();
  const approver = await approverContext.newPage();
  try {
    await loginAndSelectTenant(requester, account.email, account.password);
    await requester.goto('/workflows/requests');
    await expect(requester.getByRole('heading', { name: 'طلبات سير العمل' })).toBeVisible();
    await requester.getByLabel('العنوان').fill('طلب اعتماد تجريبي');
    await requester.getByLabel('الوصف').fill('دورة اعتماد حقيقية على PostgreSQL');
    await requester.getByLabel('المعتمد').selectOption({ label: account.approver_email });
    await requester.getByRole('button', { name: 'حفظ المسودة' }).click();
    await expect(requester.getByTestId('workflow-request')).toContainText('مسودة');
    await requester.getByRole('button', { name: 'إرسال' }).click();
    await expect(requester.getByTestId('workflow-request')).toContainText('قيد الاعتماد');
    await requester.reload();
    await expect(requester.getByRole('button', { name: 'الإشعارات' })).toBeVisible();

    await loginAndSelectTenant(approver, account.approver_email, account.approver_password);
    await expect(approver.getByLabel(/إشعارات غير مقروءة/)).toBeVisible();
    await approver.getByRole('button', { name: 'الإشعارات' }).click();
    await expect(approver.getByTestId('notification-item')).toContainText('طلب جديد للاعتماد');
    await approver.getByRole('button', { name: 'فتح الطلب' }).click();
    await expect(approver).toHaveURL(/\/workflows\/requests\?request=/);
    await approver.goto('/tasks');
    await expect(approver.getByTestId('activity-task')).toContainText('طلب اعتماد تجريبي');
    await expect(approver.getByTestId('activity-task')).toContainText('مفتوحة');
    await approver.goto('/workflows/approvals');
    await expect(approver.getByTestId('approval-task')).toContainText('طلب اعتماد تجريبي');
    await approver.getByLabel('ملاحظة القرار').fill('أكمل وصف الطلب');
    await approver.getByRole('button', { name: 'إعادة' }).click();
    await expect(approver.getByText('لا توجد اعتمادات بانتظارك')).toBeVisible();

    // The proof intentionally drives two authenticated shells. Respect the
    // PostgreSQL-backed CSRF limit before the resubmission half instead of
    // resetting counters or retrying a rejected request.
    await reserveRealCsrfBudget();
    await requester.reload();
    await expect(requester.getByTestId('workflow-request')).toContainText('معاد');
    await requester.getByRole('button', { name: 'الإشعارات' }).click();
    await expect(requester.getByTestId('notification-item').first()).toContainText(
      'أعيد الطلب للتعديل',
    );
    await requester.getByRole('link', { name: 'الطلبات' }).click();
    await requester.getByRole('button', { name: 'تعديل' }).click();
    await requester.getByLabel('الوصف').fill('دورة اعتماد مكتملة وقابلة للتتبع');
    await requester.getByRole('button', { name: 'حفظ المسودة' }).click();
    await requester.getByRole('button', { name: 'إرسال' }).click();

    await approver.reload();
    await expect(approver.getByTestId('approval-task')).toBeVisible();
    await approver.getByRole('button', { name: 'اعتماد' }).click();
    await approver.goto('/tasks');
    await approver.getByLabel('الحالة').selectOption('completed');
    await approver.getByRole('button', { name: 'تطبيق' }).click();
    await expect(approver.getByTestId('activity-task').first()).toContainText('مكتملة');
    await requester.reload();
    await expect(requester.getByTestId('workflow-request')).toContainText('معتمد');
    await requester.getByRole('button', { name: 'سجل الحركات' }).click();
    await expect(requester.getByTestId('workflow-history')).toContainText('تمت الإعادة');
    await expect(requester.getByTestId('workflow-history')).toContainText('تم الاعتماد');
    await expect(requester.getByTestId('workflow-history')).toContainText('مقدم الطلب');
    await requester.getByRole('button', { name: 'الإشعارات' }).click();
    await expect(requester.getByTestId('notification-item').first()).toContainText('اعتُمد الطلب');
    await requester.getByRole('button', { name: 'تحديد الكل كمقروء' }).click();
    await expect(requester.getByText('جديد')).toHaveCount(0);
  } finally {
    for (const value of await requesterContext.cookies()) rememberSecret(value.value);
    for (const value of await approverContext.cookies()) rememberSecret(value.value);
    await requesterContext.close();
    await approverContext.close();
    await database('cleanup', account);
  }
});

test('real workflow documents use S3, respect participants, and survive submission', async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const account = await database('seed_login');
  const requesterContext = await browser.newContext({ baseURL: origin });
  const approverContext = await browser.newContext({ baseURL: origin });
  trackRealCsrfBudget(requesterContext);
  trackRealCsrfBudget(approverContext);
  const requester = await requesterContext.newPage();
  const approver = await approverContext.newPage();
  try {
    await loginAndSelectTenant(requester, account.email, account.password);
    await requester.goto('/workflows/requests');
    await requester.getByLabel('العنوان').fill('طلب مع مرفق');
    await requester.getByLabel('الوصف').fill('ملف PDF مخزن في خدمة كائنات');
    await requester.getByLabel('المعتمد').selectOption({ label: account.approver_email });
    await requester.getByRole('button', { name: 'حفظ المسودة' }).click();
    const request = requester.getByTestId('workflow-request');
    await expect(request).toContainText('طلب مع مرفق');
    const requestId = await request.getAttribute('data-request-id');
    expect(requestId).toBeTruthy();
    await request.getByRole('button', { name: 'المرفقات' }).click();
    await request.getByLabel('اختر ملفًا').setInputFiles({
      name: 'review.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF'),
    });
    await request.getByRole('button', { name: 'رفع المرفق' }).click();
    await expect(request.getByText('review.pdf')).toBeVisible();
    const download = requester.waitForEvent('download');
    await request.getByRole('button', { name: 'تنزيل' }).click();
    expect((await download).suggestedFilename()).toBe('review.pdf');
    await requester.getByRole('link', { name: 'مركز الوثائق' }).click();
    await expect(requester.getByTestId('document-center-item')).toContainText('review.pdf');
    await expect(requester.getByTestId('document-center-item')).toContainText('طلب مع مرفق');
    await requester.getByRole('button', { name: 'فتح الطلب' }).click();
    await expect(requester.getByTestId('workflow-request')).toContainText('طلب مع مرفق');
    await request.getByRole('button', { name: 'إرسال' }).click();
    await expect(request).toContainText('قيد الاعتماد');

    await loginAndSelectTenant(approver, account.approver_email, account.approver_password);
    await approver.goto('/workflows/approvals');
    const task = approver.getByTestId('approval-task');
    await expect(task).toContainText('طلب مع مرفق');
    await task.getByRole('button', { name: 'المرفقات' }).click();
    await expect(task.getByText('review.pdf')).toBeVisible();
    const approverDownload = approver.waitForEvent('download');
    await task.getByRole('button', { name: 'تنزيل' }).click();
    expect((await approverDownload).suggestedFilename()).toBe('review.pdf');
    await approver.getByRole('link', { name: 'مركز الوثائق' }).click();
    await expect(approver.getByTestId('document-center-item')).toContainText('review.pdf');
    await expect(approver.getByRole('button', { name: 'فتح الاعتماد' })).toBeVisible();

    await requester.getByRole('button', { name: 'A', exact: true }).click();
    await requester.getByRole('menuitem', { name: 'B', exact: true }).click();
    await expect(requester.getByRole('button', { name: 'B', exact: true })).toBeVisible();
    const foreign = await protectedApi(() =>
      requester.request.get(`/workflows/requests/${requestId}/documents`),
    );
    expect(foreign.status()).toBe(404);
    await requester.getByRole('link', { name: 'مركز الوثائق' }).click();
    await expect(requester.getByText('لا توجد وثائق متاحة لعضويتك في هذه الجهة.')).toBeVisible();
  } finally {
    for (const value of await requesterContext.cookies()) rememberSecret(value.value);
    for (const value of await approverContext.cookies()) rememberSecret(value.value);
    await requesterContext.close();
    await approverContext.close();
    await database('cleanup', account);
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
    const authResponses: Array<{ path: string; status: number }> = [];
    page.on('response', (response) => {
      const path = new URL(response.url()).pathname;
      if (path.startsWith('/auth/')) authResponses.push({ path, status: response.status() });
    });
    const preauthResponse = page.waitForResponse((response) =>
      response.url().endsWith('/auth/preauth'),
    );
    const loginResponse = page.waitForResponse((response) =>
      response.url().endsWith('/auth/login'),
    );
    await page.locator('button[type="submit"]').click();
    await expect
      .poll(() => authResponses, { timeout: 5000 })
      .toContainEqual({ path: '/auth/preauth', status: 204 });
    expect((await preauthResponse).status()).toBe(204);
    const login = await loginResponse;
    expect(login.status()).toBe(204);
    const loginHeaders = await login.allHeaders();
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
    await page.getByRole('button', { name: 'A', exact: true }).click();
    await expect(page.getByRole('menuitem', { name: 'B', exact: true })).toBeVisible();
    await page.getByRole('menuitem', { name: 'B', exact: true }).click();
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

test('real Tenant Admin manages tenant access and rotates a changed password', async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const account = await database('seed_login');
  const adminContext = await browser.newContext({ baseURL: origin });
  const memberContext = await browser.newContext({ baseURL: origin });
  trackRealCsrfBudget(adminContext);
  trackRealCsrfBudget(memberContext);
  const admin = await adminContext.newPage();
  const member = await memberContext.newPage();
  const changedPassword = `Changed-${account.password}`;
  rememberSecret(changedPassword);
  try {
    await loginAndSelectTenant(admin, account.email, account.password);
    await admin.goto('/settings/users');
    await expect(admin.getByRole('heading', { name: 'إدارة مستخدمي الجمعية' })).toBeVisible();
    await admin.locator('input[name="email"]').fill(account.invite_email);
    const invitationResponse = admin.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname === '/tenant-admin/users/invitations',
    );
    await admin.getByRole('button', { name: 'إضافة الدعوة' }).click();
    expect((await invitationResponse).status()).toBe(201);
    const invited = admin.getByTestId('tenant-user').filter({ hasText: account.invite_email });
    await expect(invited).toContainText('بانتظار التفعيل');
    await invited.getByRole('button', { name: 'تفعيل' }).click();
    await expect(invited).toContainText('فعال');
    await invited.getByLabel('إدارة الدور').selectOption({ label: 'Browser approver' });
    await expect(invited).toContainText('Browser approver');

    const crossTenant = await admin.evaluate(
      async ({ membership, role }) => {
        const path = '/src/auth/client.ts';
        const { authClient, HttpRequestError } = await import(path);
        try {
          return (
            await authClient.request(`/auth/memberships/${membership}/roles/${role}`, {
              method: 'PUT',
            })
          ).status;
        } catch (error) {
          if (error instanceof HttpRequestError) {
            return (error as { status: number }).status;
          }
          throw error;
        }
      },
      { membership: account.approver_membership, role: account.role_b },
    );
    expect(crossTenant).toBe(404);

    await loginAndSelectTenant(member, account.approver_email, account.approver_password);
    await member.goto('/settings/users');
    await expect(member.getByRole('heading', { name: 'غير مصرح' })).toBeVisible();
    expect((await protectedApi(() => member.request.get('/tenant-admin/users'))).status()).toBe(
      403,
    );

    const oldBearer = (await adminContext.cookies()).find(
      (cookie) => cookie.name === '__Host-sahl_session',
    )?.value;
    rememberSecret(oldBearer);
    await admin.goto('/settings/password');
    await admin.locator('input[name="currentPassword"]').fill(account.password);
    await admin.locator('input[name="newPassword"]').fill(changedPassword);
    await admin.locator('input[name="confirmPassword"]').fill(changedPassword);
    const passwordResponse = admin.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname === '/auth/password/change',
    );
    await admin.getByRole('button', { name: 'تغيير كلمة المرور' }).click();
    expect((await passwordResponse).status()).toBe(204);
    await expect(admin.getByRole('heading', { name: 'تسجيل الدخول' })).toBeVisible();
    expect(
      (
        await protectedApi(() =>
          admin.request.get('http://127.0.0.1:8010/auth/me', {
            headers: { Cookie: `__Host-sahl_session=${oldBearer}` },
          }),
        )
      ).status(),
    ).toBe(401);
    await loginAndSelectTenant(admin, account.email, changedPassword);
    await admin.goto('/settings/users');
    await expect(admin.getByRole('heading', { name: 'إدارة مستخدمي الجمعية' })).toBeVisible();

    await admin.getByRole('button', { name: 'A', exact: true }).click();
    await admin.getByRole('menuitem', { name: 'B', exact: true }).click();
    await expect(admin.getByRole('heading', { name: 'غير مصرح' })).toBeVisible();
    await expect
      .poll(async () => {
        const response = await protectedApi(() => admin.request.get('/auth/me'));
        return (await response.json()).selectedMembershipId;
      })
      .toBe(account.membership_b);
    // A full browser run may have consumed the current PostgreSQL-backed CSRF
    // window by this second session rotation. Keep the direct-route proof in a
    // fresh window rather than treating a legitimate 429 as authorization UI.
    await waitForFreshCsrfWindow();
    await admin.goto('/settings/users');
    await expect(admin.getByRole('heading', { name: 'غير مصرح' })).toBeVisible();
    expect((await protectedApi(() => admin.request.get('/tenant-admin/users'))).status()).toBe(403);
  } finally {
    for (const value of await adminContext.cookies()) rememberSecret(value.value);
    for (const value of await memberContext.cookies()) rememberSecret(value.value);
    await adminContext.close();
    await memberContext.close();
    await database('cleanup', account);
  }
});
