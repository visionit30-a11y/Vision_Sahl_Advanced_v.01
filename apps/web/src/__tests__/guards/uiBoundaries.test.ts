/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { describe, expect, it } from 'vitest';

import { PRESET_FAMILIES } from '../../ui-customization/contract/presets';
import { SEMANTIC_COLOR_TOKENS } from '../../ui-customization/contract/semanticTokens';
import { THEME_IDS } from '../../ui-customization/contract/settings';
import { SRC_ROOT, collectFiles, isTestFile, readFile, toRelative } from './walk';

const CONSUMER_DIRECTORIES = ['design-system', 'pages', 'app'];

/** The one file allowed to know which icon library is installed. */
const ICON_MODULE = 'design-system/components/Icon/Icon.tsx';

/** The only files allowed to touch browser storage directly. */
const STORAGE_OWNERS = ['ui-customization/adapters/browserUiSettingsSource.ts', 'i18n/index.ts'];

/** The only file allowed to write a customisation decision onto the document. */
const DOCUMENT_WRITER = 'ui-customization/applyUiSettings.ts';

/** Every identifier a component must never contain: identities and presets. */
const CUSTOMISATION_IDS = [
  ...THEME_IDS,
  ...new Set(PRESET_FAMILIES.flatMap((family) => [...family.ids])),
];

function consumerSources(): string[] {
  return CONSUMER_DIRECTORIES.flatMap((directory) =>
    collectFiles(`${SRC_ROOT}/${directory}`, ['.ts', '.tsx', '.css']),
  ).filter((path) => !isTestFile(path));
}

/**
 * The customisation engine only holds if the boundaries around it hold. Each
 * check below is a rule that would otherwise depend on everyone remembering it.
 */
describe('ui customisation boundaries', () => {
  it('names no identity or preset inside a component or a screen', () => {
    const offenders: string[] = [];

    for (const path of consumerSources()) {
      const source = readFile(path);
      for (const id of CUSTOMISATION_IDS) {
        if (source.includes(id)) {
          offenders.push(`${toRelative(path)}: ${id}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('imports the icon library in the Icon component only', () => {
    const offenders = collectFiles(SRC_ROOT, ['.ts', '.tsx'])
      .filter((path) => toRelative(path) !== ICON_MODULE)
      .filter((path) => /from '(?:lucide-react)'/.test(readFile(path)))
      .map(toRelative);

    expect(offenders).toEqual([]);
  });

  it('reaches browser storage from the adapters only', () => {
    const offenders = collectFiles(SRC_ROOT, ['.ts', '.tsx'])
      .filter((path) => !isTestFile(path))
      .filter((path) => !STORAGE_OWNERS.includes(toRelative(path)))
      .filter((path) => /\b(localStorage|sessionStorage)\b/.test(readFile(path)))
      .map(toRelative);

    expect(offenders).toEqual([]);
  });

  it('writes the customisation decision onto the document in one place', () => {
    const offenders = collectFiles(SRC_ROOT, ['.ts', '.tsx'])
      .filter((path) => !isTestFile(path))
      .filter((path) => toRelative(path) !== DOCUMENT_WRITER)
      .filter((path) => /\.dataset\b/.test(readFile(path)))
      .map(toRelative);

    expect(offenders).toEqual([]);
  });

  it('uses only colour tokens that exist in the contract', () => {
    const known = new Set(SEMANTIC_COLOR_TOKENS.map((token) => `--color-${token}`));
    const offenders: string[] = [];

    for (const path of collectFiles(SRC_ROOT, ['.css'])) {
      const source = readFile(path);
      for (const match of source.matchAll(/var\(\s*(--color-[a-z0-9-]+)/g)) {
        const name = match[1] ?? '';
        if (!known.has(name)) {
          offenders.push(`${toRelative(path)}: ${name}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
