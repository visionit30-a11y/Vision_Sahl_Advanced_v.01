/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { describe, expect, it } from 'vitest';

import {
  CONTRAST_INTERFACE_PAIRS,
  CONTRAST_MINIMUM_INTERFACE,
  CONTRAST_MINIMUM_TEXT,
  CONTRAST_TEXT_PAIRS,
} from '../../ui-customization/contract/semanticTokens';
import { PRESET_FAMILIES, TABLE_PRESET_IDS } from '../../ui-customization/contract/presets';
import { readPresetFiles } from './presetFiles';
import { contrastRatio, readThemeFiles } from './themeFiles';

const themes = readThemeFiles();

function valueOf(declarations: Map<string, string>, token: string): string {
  const value = declarations.get(`--color-${token}`);

  if (!value) {
    throw new Error(`Missing token --color-${token}`);
  }

  return value;
}

/**
 * WCAG AA, computed from the identity files themselves: 4.5 for text and 3 for
 * interface elements. Reviewing five palettes by eye is how an unreadable
 * screen reaches an association nobody tested on.
 */
describe('WCAG AA contrast', () => {
  it('meets 4.5:1 for every text pair in every identity', () => {
    const offenders: string[] = [];

    for (const theme of themes) {
      for (const [foreground, background] of CONTRAST_TEXT_PAIRS) {
        const ratio = contrastRatio(
          valueOf(theme.declarations, foreground),
          valueOf(theme.declarations, background),
        );

        if (ratio < CONTRAST_MINIMUM_TEXT) {
          offenders.push(`${theme.id}: ${foreground} on ${background} = ${ratio.toFixed(2)}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('meets 3:1 for every interface pair in every identity', () => {
    const offenders: string[] = [];

    for (const theme of themes) {
      for (const [foreground, background] of CONTRAST_INTERFACE_PAIRS) {
        const ratio = contrastRatio(
          valueOf(theme.declarations, foreground),
          valueOf(theme.declarations, background),
        );

        if (ratio < CONTRAST_MINIMUM_INTERFACE) {
          offenders.push(`${theme.id}: ${foreground} on ${background} = ${ratio.toFixed(2)}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});

/**
 * A rule that exists because of a measurement, not a preference: the strong
 * border token reads at 2.61 against the subtle background across the five
 * identities, where three is the bar for a non text element. So a table preset
 * that draws its grid in the strong border may not tint the surfaces that grid
 * runs across.
 *
 * Written as a test rather than a note, because the person who adds the sixth
 * table preset will not have read the note.
 */
describe('table grid over tinted surfaces', () => {
  const tables = PRESET_FAMILIES.filter((family) => family.key === 'tablePreset');
  const UNTINTED = ['transparent', 'var(--color-bg-surface)'];
  const TINTABLE = ['--table-header-bg', '--table-stripe-bg', '--table-total-row-bg'];

  it('keeps the strong border off every tinted surface', () => {
    expect(tables).toHaveLength(1);
    const offenders: string[] = [];

    for (const preset of tables.flatMap(readPresetFiles)) {
      const border = preset.declarations.get('--table-border-color') ?? '';
      if (!border.includes('border-strong')) {
        continue;
      }

      for (const name of TINTABLE) {
        const value = preset.declarations.get(name) ?? '';
        if (!UNTINTED.includes(value)) {
          offenders.push(`${preset.id}: ${name} = ${value}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('checks every table preset, so the rule cannot be skipped by adding one', () => {
    expect(tables.flatMap(readPresetFiles).map((preset) => preset.id)).toEqual(
      [...TABLE_PRESET_IDS].sort(),
    );
  });
});
