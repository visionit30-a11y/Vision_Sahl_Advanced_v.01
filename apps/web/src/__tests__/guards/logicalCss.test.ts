/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { describe, expect, it } from 'vitest';

import { SRC_ROOT, collectFiles, readFile, toRelative } from './walk';

const PHYSICAL_PROPERTIES = [
  /(^|[\s;{])(left|right)\s*:/gm,
  /\b(margin|padding)-(left|right)\s*:/g,
  /\bborder-(left|right)(-[a-z]+)?\s*:/g,
  /\btext-align\s*:\s*(left|right)/g,
  /\bfloat\s*:\s*(left|right)/g,
];

/**
 * One stylesheet must serve both directions. Physical properties would force a
 * second, mirrored set of rules, which the language contract rules out.
 */
describe('logical CSS only', () => {
  it('uses no direction specific physical properties', () => {
    const offenders: string[] = [];

    for (const path of collectFiles(SRC_ROOT, ['.css'])) {
      const source = readFile(path);
      for (const pattern of PHYSICAL_PROPERTIES) {
        for (const match of source.matchAll(pattern)) {
          offenders.push(`${toRelative(path)}: ${match[0].trim()}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
