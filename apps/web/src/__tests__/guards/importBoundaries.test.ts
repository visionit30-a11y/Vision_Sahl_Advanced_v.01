/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { describe, expect, it } from 'vitest';

import { SRC_ROOT, collectFiles, readFile, toRelative } from './walk';

/**
 * Screens consume the design system through its single entry point. Reaching
 * into a component file couples a screen to the library's internal layout.
 */
describe('design system import boundary', () => {
  it('lets screens import the library only through its entry point', () => {
    const offenders: string[] = [];

    for (const directory of ['pages', 'app']) {
      for (const path of collectFiles(`${SRC_ROOT}/${directory}`, ['.ts', '.tsx'])) {
        const source = readFile(path);
        for (const match of source.matchAll(/from '(?:\.\.\/)+design-system\/[^']+'/g)) {
          offenders.push(`${toRelative(path)}: ${match[0]}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
