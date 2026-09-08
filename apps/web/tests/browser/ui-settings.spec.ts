import { expect, test } from '@playwright/test';

// Real Chromium against the existing HTTP contract fixture, not a production DB proof.
test.beforeEach(async ({ page }) => {
  await page.request.get('/auth/test/session');
  await page.goto('/design-system');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'navy-institutional');
  await expect(page.locator('input[value="sand-warm"]')).toBeEnabled();
});

test('server user override survives refresh and deletion restores inheritance', async ({
  page,
}) => {
  await page.locator('input[value="sand-warm"]').check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'sand-warm');
  const effective = page.waitForResponse((response) =>
    response.url().endsWith('/ui-settings/effective'),
  );
  await page.reload();
  await effective;
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'sand-warm');
  await page.getByRole('button', { name: 'العودة إلى الموروث' }).first().click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'navy-institutional');
  await page.locator('input[value="tenant"]').check();
  await page.locator('input[value="slate-neutral"]').check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'slate-neutral');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'slate-neutral');
});

test('tenant switch rotates cookie and refreshes both tabs without stale settings', async ({
  page,
  context,
}) => {
  const other = await context.newPage();
  await other.goto('/design-system');
  await expect(other.locator('html')).toHaveAttribute('data-theme', 'navy-institutional');
  await page.locator('input[value="sand-warm"]').check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'sand-warm');
  const cookiesBefore = await context.cookies();
  await page.evaluate(async () => {
    const path = '/src/auth/client.ts';
    const { authClient } = await import(path);
    await authClient.switchTenant('membership-2');
  });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'green-institutional');
  await expect(other.locator('html')).toHaveAttribute('data-theme', 'green-institutional');
  const cookiesAfter = await context.cookies();
  // Return only a boolean on failure: never include the bearer in artifacts.
  expect(cookiesBefore[0]?.value !== cookiesAfter[0]?.value).toBe(true);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'green-institutional');
});

test('409 visibly blocks writes until reload and 401 removes old state', async ({ page }) => {
  await page.evaluate(async () => {
    const path = '/src/auth/client.ts';
    const { authClient } = await import(path);
    await authClient.request('/ui-settings/tenant', {
      method: 'PUT',
      body: JSON.stringify({ settings: { theme: 'slate-neutral' }, expected_version: 1 }),
    });
  });
  await page.locator('input[value="tenant"]').check();
  await page.locator('input[value="sand-warm"]').check();
  await expect(page.getByText('تغيرت الإعدادات. أعد جلبها قبل المحاولة مجددًا.')).toBeVisible();
  await expect(page.locator('input[value="sand-warm"]')).toHaveCount(0);
  await page.getByRole('button', { name: 'إعادة جلب الإعدادات' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'slate-neutral');
  await page.evaluate(async () => {
    const path = '/src/auth/client.ts';
    const { authClient } = await import(path);
    await authClient.logout();
  });
  await expect(page.getByText('سجّل الدخول لتحميل الإعدادات')).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'teal-calm');
  await expect(page.locator('input[value="sand-warm"]')).toHaveCount(0);
});

test('403 hides tenant writes and storage/console contain no settings or secrets', async ({
  page,
}) => {
  await page.request.get('/auth/test/session?tenant_write=0');
  await page.reload();
  await expect(page.locator('input[value="sand-warm"]')).toBeEnabled();
  await page.locator('input[value="tenant"]').check();
  await expect(page.getByText('طبقة الصلاحيات لا تسمح بتعديل هذا النطاق.')).toBeVisible();
  await expect(page.locator('input[value="sand-warm"]')).toHaveCount(0);
  await expect(page.locator('input[value="platform"]')).toHaveCount(0);
  const logs: string[] = [];
  page.on('console', (message) => logs.push(message.text()));
  await page.locator('input[value="user"]').check();
  await page.locator('input[value="sand-warm"]').check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'sand-warm');
  const empty = await page.evaluate(
    async () =>
      localStorage.length === 0 &&
      sessionStorage.length === 0 &&
      (await indexedDB.databases()).length === 0 &&
      document.cookie === '',
  );
  expect(empty).toBe(true);
  expect(logs.some((message) => /bearer|csrf|sahl_session|sand-warm/.test(message))).toBe(false);
});
