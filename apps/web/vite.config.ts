import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const API_TARGET = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8010';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // The dev server proxies the API so the browser always talks to one origin.
    proxy: {
      '/ui-settings': { target: API_TARGET, changeOrigin: false },
      '/health': { target: API_TARGET, changeOrigin: false },
      '/auth': { target: API_TARGET, changeOrigin: false },
      '/workflows': {
        target: API_TARGET,
        changeOrigin: false,
        // The SPA owns the same visible route prefix. HTML navigations stay in
        // Vite while JSON API requests cross the local reverse proxy.
        bypass: (request) =>
          request.headers.accept?.includes('text/html') ? request.url : undefined,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
});
