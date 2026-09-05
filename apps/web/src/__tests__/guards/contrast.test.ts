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
