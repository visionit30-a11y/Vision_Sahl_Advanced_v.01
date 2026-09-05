import { screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import i18n from '../i18n';
import { HomePage } from '../pages/HomePage';
import { renderWithProviders } from '../test/renderWithProviders';

const RESPONSES: Record<string, unknown> = {
  '/health': {
    status: 'ok',
    name: 'Sahl Developer Platform',
    version: '0.1.0',
    environment: 'test',
  },
  '/health/db': { dependency: 'postgresql', status: 'up', detail: null },
  '/health/redis': {
    dependency: 'redis',
    status: 'disabled',
    detail: 'Redis is not enabled in this environment (see ADR-0003).',
  },
};

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const body = RESPONSES[String(input)];
      if (!body) {
        throw new Error(`Unexpected request: ${String(input)}`);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
      } as Response);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('home page', () => {
  it('lists the platform services', async () => {
    renderWithProviders(<HomePage />);

    expect(await screen.findByText(i18n.t('home:services.application'))).toBeInTheDocument();
    expect(screen.getByText(i18n.t('home:services.database'))).toBeInTheDocument();
    expect(screen.getByText(i18n.t('home:services.cache'))).toBeInTheDocument();
  });

  it('reports a disabled cache as disabled rather than failed', async () => {
    renderWithProviders(<HomePage />);

    expect(await screen.findByText(i18n.t('home:serviceState.disabled'))).toBeInTheDocument();
    expect(screen.queryByText(i18n.t('home:serviceState.down'))).not.toBeInTheDocument();
  });
});
