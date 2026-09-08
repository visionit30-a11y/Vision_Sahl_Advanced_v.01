import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  testMatch: '**/real-backend.spec.ts',
  workers: 1,
  retries: 0,
  reporter: 'line',
  use: {
    baseURL: 'http://localhost:5187',
    browserName: 'chromium',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  webServer: {
    command:
      'node tests/browser/real-backend-preflight.mjs && npm run dev -- --host localhost --port 5187 --strictPort',
    url: 'http://localhost:5187',
    reuseExistingServer: false,
    env: { VITE_API_PROXY_TARGET: 'http://127.0.0.1:8010' },
  },
});
