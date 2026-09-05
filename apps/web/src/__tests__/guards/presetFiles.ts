import { join } from 'node:path';

import { PRESET_FAMILIES } from '../../ui-customization/contract/presets';
import type { PresetFamily } from '../../ui-customization/contract/presets';
import { SRC_ROOT, collectFiles, readFile, toRelative } from './walk';

export const PRESETS_DIRECTORY = join(SRC_ROOT, 'styles', 'presets');

export function familyDirectory(family: PresetFamily): string {
  return join(PRESETS_DIRECTORY, family.directory);
}

export interface CssRule {
  selectors: string[];
  declarations: Map<string, string>;
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '');
}

/**
 * A small rule reader. Preset and identity stylesheets are flat lists of custom
 * property declarations, so nothing here needs to understand nesting - and a
 * file that did contain nesting would fail the guards, which is the point.
 */
export function parseRules(source: string): CssRule[] {
  const rules: CssRule[] = [];

  for (const match of stripComments(source).matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const declarations = new Map<string, string>();

    for (const part of (match[2] ?? '').split(';')) {
      const separator = part.indexOf(':');
      if (separator === -1) {
        continue;
      }
      declarations.set(part.slice(0, separator).trim(), part.slice(separator + 1).trim());
    }

    rules.push({
      selectors: (match[1] ?? '')
        .split(',')
        .map((selector) => selector.trim())
        .filter(Boolean),
      declarations,
    });
  }

  return rules;
}

export interface PresetFile {
  family: PresetFamily;
  /** Taken from the file name, which the guards check against the selector. */
  id: string;
  path: string;
  relativePath: string;
  selectors: string[];
  declarations: Map<string, string>;
  targetsRoot: boolean;
}

/** Reads one family's stylesheets as data, so a value edited in CSS is checked. */
export function readPresetFiles(family: PresetFamily): PresetFile[] {
  return collectFiles(familyDirectory(family), ['.css'])
    .filter((path) => !path.endsWith('index.css'))
    .map((path) => {
      const rules = parseRules(readFile(path));
      const declarations = new Map<string, string>();
      const selectors: string[] = [];

      for (const rule of rules) {
        for (const [name, value] of rule.declarations) {
          declarations.set(name, value);
        }
        selectors.push(...rule.selectors);
      }

      const relativePath = toRelative(path);

      return {
        family,
        id:
          relativePath
            .split('/')
            .pop()
            ?.replace(/\.css$/, '') ?? '',
        path,
        relativePath,
        selectors: selectors.filter((selector) => selector !== ':root'),
        declarations,
        targetsRoot: selectors.includes(':root'),
      };
    })
    .sort((left, right) => left.id.localeCompare(right.id));
}

export function everyPresetFile(): PresetFile[] {
  return PRESET_FAMILIES.flatMap((family) => readPresetFiles(family));
}
