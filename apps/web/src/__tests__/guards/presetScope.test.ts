/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { describe, expect, it } from 'vitest';

import { PRESET_FAMILIES } from '../../ui-customization/contract/presets';
import { PRESETS_DIRECTORY, everyPresetFile, parseRules } from './presetFiles';
import { collectFiles, readFile, toRelative } from './walk';

/**
 * A preset owns form and nothing else. These checks are what turn that sentence
 * from an agreement into a property of the codebase: an identity cannot grow a
 * shape, a preset cannot grow a colour, and neither can reach into the other's
 * namespace or into the shared layout tokens.
 */
describe('preset scope', () => {
  const presets = everyPresetFile();

  it('declares its own family prefix and nothing else', () => {
    const offenders: string[] = [];

    for (const preset of presets) {
      for (const name of preset.declarations.keys()) {
        if (!name.startsWith(preset.family.prefix)) {
          offenders.push(`${preset.relativePath}: ${name}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('declares no colour token, so an identity is never overridden by a shape', () => {
    const offenders: string[] = [];

    for (const preset of presets) {
      for (const name of preset.declarations.keys()) {
        if (name.startsWith('--color-')) {
          offenders.push(`${preset.relativePath}: ${name}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('declares no shared layout token, so the reserved status band stays fixed', () => {
    const offenders: string[] = [];
    const shared = ['--size-', '--space-', '--radius-', '--shadow-', '--font-', '--layer-'];

    for (const preset of presets) {
      for (const name of preset.declarations.keys()) {
        if (shared.some((prefix) => name.startsWith(prefix))) {
          offenders.push(`${preset.relativePath}: ${name}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('declares custom properties only, so a preset holds no layout rule at all', () => {
    const offenders: string[] = [];

    for (const path of collectFiles(PRESETS_DIRECTORY, ['.css'])) {
      for (const rule of parseRules(readFile(path))) {
        for (const name of rule.declarations.keys()) {
          if (!name.startsWith('--')) {
            offenders.push(`${toRelative(path)}: ${name}`);
          }
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it('keeps every family in its own directory', () => {
    for (const family of PRESET_FAMILIES) {
      const strays = presets
        .filter((preset) => preset.family.key === family.key)
        .filter((preset) => !preset.relativePath.includes(`/presets/${family.directory}/`))
        .map((preset) => preset.relativePath);

      expect({ family: family.key, strays }).toEqual({ family: family.key, strays: [] });
    }
  });

  it('holds no code, so a preset cannot change behaviour', () => {
    expect(collectFiles(PRESETS_DIRECTORY, ['.ts', '.tsx', '.js']).map(toRelative)).toEqual([]);
  });
});
