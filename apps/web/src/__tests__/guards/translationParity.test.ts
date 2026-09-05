import { describe, expect, it } from 'vitest';

import { SRC_ROOT, collectFiles, readFile, toRelative } from './walk';

function flatten(value: unknown, prefix = ''): string[] {
  if (value === null || typeof value !== 'object') {
    return [prefix];
  }

  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    flatten(child, prefix ? `${prefix}.${key}` : key),
  );
}

function keysOf(language: 'ar' | 'en'): Record<string, string[]> {
  const root = `${SRC_ROOT}/i18n/locales/${language}`;
  const result: Record<string, string[]> = {};

  for (const path of collectFiles(root, ['.json'])) {
    const namespace = toRelative(path).split('/').pop() ?? path;
    result[namespace] = flatten(JSON.parse(readFile(path))).sort();
  }

  return result;
}

/** Arabic and English must stay in step; a missing key is a broken screen. */
describe('translation parity', () => {
  it('has the same namespaces in both languages', () => {
    expect(Object.keys(keysOf('ar')).sort()).toEqual(Object.keys(keysOf('en')).sort());
  });

  it('has the same keys in every namespace', () => {
    const arabic = keysOf('ar');
    const english = keysOf('en');

    for (const namespace of Object.keys(arabic)) {
      expect({ namespace, keys: arabic[namespace] }).toEqual({
        namespace,
        keys: english[namespace],
      });
    }
  });
});
