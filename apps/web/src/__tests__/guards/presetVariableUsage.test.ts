/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { describe, expect, it } from 'vitest';

import { PRESET_FAMILIES } from '../../ui-customization/contract/presets';
import { SRC_ROOT, collectFiles, readFile, toRelative } from './walk';

const stylesheets = collectFiles(SRC_ROOT, ['.css']);

/**
 * Both directions matter. A misspelt variable resolves to nothing and the rule
 * quietly disappears, which is the kind of defect that reaches review looking
 * fine; a variable nobody reads is a contract that has outlived its use and
 * will drift.
 */
describe('preset variable usage', () => {
  const known = new Set(PRESET_FAMILIES.flatMap((family) => [...family.variables]));
  const prefixes = PRESET_FAMILIES.map((family) => family.prefix);

  it('uses only variables that exist in a family contract', () => {
    const offenders: string[] = [];

    for (const path of stylesheets) {
      for (const match of readFile(path).matchAll(/var\(\s*(--[a-z0-9-]+)/g)) {
        const name = match[1] ?? '';
        if (prefixes.some((prefix) => name.startsWith(prefix)) && !known.has(name)) {
          offenders.push(`${toRelative(path)}: ${name}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('has no variable in a contract that nothing reads', () => {
    const used = new Set<string>();

    for (const path of stylesheets) {
      for (const match of readFile(path).matchAll(/var\(\s*(--[a-z0-9-]+)/g)) {
        used.add(match[1] ?? '');
      }
    }

    for (const family of PRESET_FAMILIES) {
      const unread = family.variables.filter((variable) => !used.has(variable));
      expect({ family: family.key, unread }).toEqual({ family: family.key, unread: [] });
    }
  });
});
