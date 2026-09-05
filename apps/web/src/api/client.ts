/**
 * Minimal API client for the Phase 0 verification page.
 * Replaced in Phase 1 by the shared data-fetching layer.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

export type DependencyState = 'up' | 'down' | 'disabled';

export interface ApplicationHealth {
  status: string;
  name: string;
  version: string;
  environment: string;
}

export interface DependencyHealth {
  dependency: string;
  status: DependencyState;
  detail: string | null;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { Accept: 'application/json' },
  });

  // 503 still carries a valid dependency payload, so it is data, not a failure.
  if (!response.ok && response.status !== 503) {
    throw new Error(`Request to ${path} failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

export function fetchApplicationHealth(): Promise<ApplicationHealth> {
  return getJson<ApplicationHealth>('/health');
}

export function fetchDatabaseHealth(): Promise<DependencyHealth> {
  return getJson<DependencyHealth>('/health/db');
}

export function fetchCacheHealth(): Promise<DependencyHealth> {
  return getJson<DependencyHealth>('/health/redis');
}
