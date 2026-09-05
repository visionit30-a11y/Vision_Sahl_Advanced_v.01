/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { describe, expect, it } from 'vitest';

import { SRC_ROOT, collectFiles, isTestFile, readFile, toRelative } from './walk';

const SPECIMENS_DIRECTORY = `${SRC_ROOT}/pages/design-system/specimens`;

/** Hooks that would turn a specimen into something with a life of its own. */
const FORBIDDEN_HOOKS = ['useState', 'useReducer', 'useEffect', 'useLayoutEffect', 'useRef'];

/**
 * The specimens exist to prove the table and print contracts on screen while no
 * engine exists. These checks are what keep them specimens: the day one of them
 * takes a prop, holds state or fetches a row, it has started becoming the
 * engine this phase deliberately does not build.
 */
describe('specimen purity', () => {
  const specimens = collectFiles(SPECIMENS_DIRECTORY, ['.tsx']);

  it('has specimens to check at all', () => {
    expect(specimens.length).toBeGreaterThan(0);
  });

  it('takes no props', () => {
    const offenders: string[] = [];

    for (const path of specimens) {
      for (const match of readFile(path).matchAll(/export function (\w+)\(([^)]*)\)/g)) {
        if ((match[2] ?? '').trim() !== '') {
          offenders.push(`${toRelative(path)}: ${match[1] ?? ''}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('holds no state, no effect and no reference', () => {
    const offenders: string[] = [];

    for (const path of specimens) {
      const source = readFile(path);
      for (const hook of FORBIDDEN_HOOKS) {
        if (new RegExp(`\\b${hook}\\b`).test(source)) {
          offenders.push(`${toRelative(path)}: ${hook}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('loads no data', () => {
    const offenders: string[] = [];

    for (const path of specimens) {
      const source = readFile(path);
      if (/\bfetch\s*\(/.test(source) || /from '.*api\//.test(source)) {
        offenders.push(toRelative(path));
      }
    }

    expect(offenders).toEqual([]);
  });

  it('is not exported from the design system', () => {
    const barrel = readFile(`${SRC_ROOT}/design-system/index.ts`);

    expect(barrel.includes('Specimen')).toBe(false);
  });

  it('is imported by the design system page only', () => {
    // Tests import them on purpose; production code outside the page may not.
    const offenders = collectFiles(SRC_ROOT, ['.ts', '.tsx'])
      .filter((path) => !isTestFile(path))
      .filter((path) => !toRelative(path).startsWith('pages/'))
      .filter((path) => /from '[^']*specimens\//.test(readFile(path)))
      .map(toRelative);

    expect(offenders).toEqual([]);
  });
});
