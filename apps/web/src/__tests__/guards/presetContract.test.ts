/**
 * @vitest-environment node
 *
 * A filesystem guard: it inspects sources, never the DOM.
 */
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { PRESET_FAMILIES } from '../../ui-customization/contract/presets';
import { alertPresetRegistry } from '../../ui-customization/registries/alertPresetRegistry';
import { buttonPresetRegistry } from '../../ui-customization/registries/buttonPresetRegistry';
import { overlayPresetRegistry } from '../../ui-customization/registries/overlayPresetRegistry';
import { printPresetRegistry } from '../../ui-customization/registries/printPresetRegistry';
import { tablePresetRegistry } from '../../ui-customization/registries/tablePresetRegistry';
import { familyDirectory, readPresetFiles } from './presetFiles';
import { readFile } from './walk';

const REGISTRIES = {
  buttonPreset: buttonPresetRegistry,
  alertPreset: alertPresetRegistry,
  overlayPreset: overlayPresetRegistry,
  tablePreset: tablePresetRegistry,
  printPreset: printPresetRegistry,
};

/**
 * A preset family is a contract, not a folder of stylesheets. If a preset may
 * forget or invent a variable, a component falls back to nothing on the one
 * preset nobody opened during review.
 */
describe.each(PRESET_FAMILIES)('$key contract', (family) => {
  const presets = readPresetFiles(family);

  it('has one stylesheet for every registered preset and no orphan on either side', () => {
    expect(presets.map((preset) => preset.id)).toEqual([...family.ids].sort());
    expect([...REGISTRIES[family.key].ids()].sort()).toEqual([...family.ids].sort());
  });

  it('targets its own preset attribute in every stylesheet', () => {
    for (const preset of presets) {
      expect({ file: preset.relativePath, selectors: preset.selectors }).toEqual({
        file: preset.relativePath,
        selectors: [`[${family.dataAttribute}='${preset.id}']`],
      });
    }
  });

  it('defines exactly the family variable contract in every preset', () => {
    const expected = [...family.variables].sort();

    for (const preset of presets) {
      expect({ preset: preset.id, variables: [...preset.declarations.keys()].sort() }).toEqual({
        preset: preset.id,
        variables: expected,
      });
    }
  });

  it('applies the built-in preset to the document root as well', () => {
    for (const preset of presets) {
      expect({ preset: preset.id, targetsRoot: preset.targetsRoot }).toEqual({
        preset: preset.id,
        targetsRoot: preset.id === family.builtIn,
      });
    }
  });

  it('loads every stylesheet from the family entry point', () => {
    const index = readFile(join(familyDirectory(family), 'index.css'));

    for (const preset of presets) {
      expect({ preset: preset.id, imported: index.includes(`./${preset.id}.css`) }).toEqual({
        preset: preset.id,
        imported: true,
      });
    }
  });
});
