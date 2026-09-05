/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { describe, expect, it } from 'vitest';

import { PRESET_FAMILIES } from '../../ui-customization/contract/presets';
import { PRESETS_DIRECTORY } from './presetFiles';
import { SRC_ROOT, collectFiles, readFile, toRelative } from './walk';

const PRINT_STYLESHEET = `${SRC_ROOT}/styles/print.css`;

/**
 * A custom property is not read inside @page: the page context does not inherit
 * from the document root. So page margins are padding on the print container,
 * and the one neutral @page lives here rather than in a preset - which is what
 * keeps "a preset file holds values only" true.
 */
describe('print stylesheet', () => {
  it('keeps every page rule out of the preset files', () => {
    const offenders = collectFiles(PRESETS_DIRECTORY, ['.css'])
      .filter((path) =>
        readFile(path)
          .replace(/\/\*[\s\S]*?\*\//g, '')
          .includes('@page'),
      )
      .map(toRelative);

    expect(offenders).toEqual([]);
  });

  it('declares the page rule exactly once, in the print stylesheet', () => {
    const holders = collectFiles(SRC_ROOT, ['.css'])
      .filter((path) =>
        readFile(path)
          .replace(/\/\*[\s\S]*?\*\//g, '')
          .includes('@page'),
      )
      .map(toRelative);

    expect(holders).toEqual(['styles/print.css']);
  });

  it('declares no literal colour of its own', () => {
    const source = readFile(PRINT_STYLESHEET);
    const offenders = [...source.matchAll(/#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?)\(/g)].map(
      (match) => match[0],
    );

    expect(offenders).toEqual([]);
  });

  it('isolates the printed surface only when the page carries one', () => {
    const source = readFile(PRINT_STYLESHEET);

    // Without the :has() condition, a screen with no print surface would print
    // a blank sheet - a side effect nobody would discover until they printed.
    expect(source).toContain(':has([data-print-surface])');
  });

  it('reads print values from the family contract', () => {
    const contract = new Set(
      PRESET_FAMILIES.filter((family) => family.key === 'printPreset').flatMap((family) => [
        ...family.variables,
      ]),
    );
    const offenders: string[] = [];

    for (const match of readFile(PRINT_STYLESHEET).matchAll(/var\(\s*(--print-[a-z0-9-]+)/g)) {
      const name = match[1] ?? '';
      if (!contract.has(name)) {
        offenders.push(name);
      }
    }

    expect(offenders).toEqual([]);
  });
});
