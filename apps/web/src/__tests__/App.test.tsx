import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '../App';

const RESPONSES: Record<string, { status: number; body: unknown }> = {
  '/health': {
    status: 200,
    body: { status: 'ok', name: 'Sahl Developer Platform', version: '0.1.0', environment: 'test' },
  },
  '/health/db': {
    status: 200,
    body: { dependency: 'postgresql', status: 'up', detail: null },
  },
  '/health/redis': {
    status: 200,
    body: { dependency: 'redis', status: 'disabled', detail: 'Redis is not enabled.' },
  },
};

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const route = RESPONSES[String(input)];
      if (!route) {
        throw new Error(`Unexpected request: ${String(input)}`);
      }
      return {
        ok: route.status < 400,
        status: route.status,
        json: async () => route.body,
      } as Response;
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Phase 0 verification page', () => {
  it('reports the application as running', async () => {
    render(<App />);

    const running = await screen.findAllByText('يعمل');
    expect(running).toHaveLength(2);
  });

  it('reports Redis as disabled instead of pretending it is healthy', async () => {
    render(<App />);

    expect(await screen.findByText('غير مفعّل في هذه المرحلة')).toBeInTheDocument();
    expect(screen.queryByText('غير متاح')).not.toBeInTheDocument();
  });

  it('lists the three checks', async () => {
    render(<App />);

    await screen.findAllByText('يعمل');
    expect(screen.getByText('التطبيق')).toBeInTheDocument();
    expect(screen.getByText('قاعدة البيانات (PostgreSQL)')).toBeInTheDocument();
    expect(screen.getByText('الذاكرة المؤقتة (Redis)')).toBeInTheDocument();
  });
});
