import { describe, expect, it } from 'vitest';

import { SRC_ROOT, collectFiles, isTestFile, readFile, toRelative } from './walk';

const ARABIC = /[؀-ۿ]/;

/**
 * Every visible string must come from the translation layer. Arabic characters
 * inside source files are the clearest sign that a label was written into a
 * component, so they are rejected outright outside the locale files.
 */
describe('no hard-coded interface text', () => {
  it('keeps Arabic characters out of TypeScript sources', () => {
    const offenders = collectFiles(SRC_ROOT, ['.ts', '.tsx'])
      .filter((path) => !toRelative(path).startsWith('i18n/locales/'))
      .filter((path) => !isTestFile(path))
      .filter((path) => ARABIC.test(readFile(path)))
      .map(toRelative);

    expect(offenders).toEqual([]);
  });

  it('keeps sentence text out of JSX bodies', () => {
    const jsxText = />\s*([^<>{}\n]*[A-Za-z][^<>{}\n]*)\s*</g;
    const offenders: string[] = [];

    for (const path of collectFiles(SRC_ROOT, ['.tsx']).filter((path) => !isTestFile(path))) {
      const source = readFile(path);
      for (const match of source.matchAll(jsxText)) {
        const text = (match[1] ?? '').trim();
        // Three or more letters in a row reads as a sentence, not punctuation.
        if (/[A-Za-z]{3,}/.test(text)) {
          offenders.push(`${toRelative(path)}: ${text}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
