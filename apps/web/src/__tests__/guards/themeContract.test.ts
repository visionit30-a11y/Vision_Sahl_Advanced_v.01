/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { SEMANTIC_COLOR_TOKENS } from '../../ui-customization/contract/semanticTokens';
import { BUILT_IN_UI_SETTINGS, THEME_IDS } from '../../ui-customization/contract/settings';
import { themeRegistry } from '../../ui-customization/registries/themeRegistry';
import { THEMES_DIRECTORY, readThemeFiles } from './themeFiles';
import { readFile } from './walk';

const themes = readThemeFiles();
const expectedTokens = SEMANTIC_COLOR_TOKENS.map((token) => `--color-${token}`).sort();

/**
 * An identity is a contract, not a mood board. If a theme may invent or forget
 * a token, a screen breaks only for whoever picked that theme, and only on the
 * screen nobody opened during review.
 */
describe('theme contract', () => {
  it('has one stylesheet for every registered identity and no orphan on either side', () => {
    expect(themes.map((theme) => theme.id)).toEqual([...THEME_IDS].sort());
    expect([...themeRegistry.ids()].sort()).toEqual([...THEME_IDS].sort());
  });

  it('targets its own identity attribute in every stylesheet', () => {
    for (const theme of themes) {
      expect({ file: theme.relativePath, selectors: theme.selectors }).toEqual({
        file: theme.relativePath,
        selectors: [theme.id],
      });
    }
  });

  it('defines exactly the semantic token contract in every identity', () => {
    for (const theme of themes) {
      expect({ theme: theme.id, tokens: [...theme.declarations.keys()].sort() }).toEqual({
        theme: theme.id,
        tokens: expectedTokens,
      });
    }
  });

  it('declares colours only, so an identity has nothing to shift', () => {
    const offenders: string[] = [];

    for (const theme of themes) {
      for (const name of theme.declarations.keys()) {
        if (!name.startsWith('--color-')) {
          offenders.push(`${theme.relativePath}: ${name}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('applies the built-in identity to the document root as well', () => {
    for (const theme of themes) {
      const source = readFile(theme.path);
      const targetsRoot = /(^|\s|,):root\b/m.test(source);

      expect({ theme: theme.id, targetsRoot }).toEqual({
        theme: theme.id,
        targetsRoot: theme.id === BUILT_IN_UI_SETTINGS.theme,
      });
    }
  });

  it('loads every identity stylesheet from the themes entry point', () => {
    const index = readFile(join(THEMES_DIRECTORY, 'index.css'));

    for (const theme of themes) {
      expect({ theme: theme.id, imported: index.includes(`./${theme.id}.css`) }).toEqual({
        theme: theme.id,
        imported: true,
      });
    }
  });
});
