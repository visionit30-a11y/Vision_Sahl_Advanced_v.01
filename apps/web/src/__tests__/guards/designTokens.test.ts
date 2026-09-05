/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { describe, expect, it } from 'vitest';

import { SRC_ROOT, collectFiles, readFile, toRelative } from './walk';

const APPROVED_BREAKPOINTS = new Set(['640', '1024', '1440']);

/**
 * Components read colours from semantic tokens and lay out against the agreed
 * breakpoints. A literal colour or an invented breakpoint is drift.
 */
describe('design tokens', () => {
  const moduleStyles = collectFiles(SRC_ROOT, ['.module.css']);

  it('declares no literal colour inside a component stylesheet', () => {
    const offenders: string[] = [];

    for (const path of moduleStyles) {
      const source = readFile(path);
      for (const match of source.matchAll(/#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?)\(/g)) {
        offenders.push(`${toRelative(path)}: ${match[0]}`);
      }
    }

    expect(offenders).toEqual([]);
  });

  it('uses only the approved breakpoints', () => {
    const offenders: string[] = [];

    for (const path of collectFiles(SRC_ROOT, ['.css'])) {
      const source = readFile(path);
      for (const match of source.matchAll(/@media\s*\(\s*min-width:\s*(\d+)px/g)) {
        const value = match[1] ?? '';
        if (!APPROVED_BREAKPOINTS.has(value)) {
          offenders.push(`${toRelative(path)}: ${value}px`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
