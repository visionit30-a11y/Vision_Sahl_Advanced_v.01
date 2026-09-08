import { defineConfig } from '@playwright/test';

const verifyLocalDev = process.env.SAHL_VERIFY_LOCAL_DEV === '1';
const port = verifyLocalDev ? 5173 : 5187;

export default defineConfig({
  testDir: './tests/browser',
  testMatch: '**/real-backend.spec.ts',
  workers: 1,
  retries: 0,
  reporter: 'line',
  use: {
    baseURL: `http://localhost:${port}`,
    browserName: 'chromium',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  // The explicit local-dev proof uses the already verified, project-owned server.
  // It never starts, replaces, or stops a process on 5173.
  webServer: verifyLocalDev
    ? undefined
    : {
        command: `node tests/browser/real-backend-preflight.mjs && npm run dev -- --host localhost --port ${port} --strictPort`,
        url: `http://localhost:${port}`,
        reuseExistingServer: false,
        env: { VITE_API_PROXY_TARGET: 'http://127.0.0.1:8010' },
      },
});
