import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const API_TARGET = 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // The dev server proxies the API so the browser always talks to one origin.
    proxy: {
      '/health': { target: API_TARGET, changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
