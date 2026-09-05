import { createRegistry } from './createRegistry';
import type { Registry, RegistryEntry } from './createRegistry';

/**
 * Metadata only, exactly like the theme registry: an identifier and two
 * translation keys. The values live in styles/presets/, which is what lets a
 * preset change repaint the page without React re-rendering anything.
 */
export interface PresetDefinition extends RegistryEntry {
  labelKey: string;
  descriptionKey: string;
}

/**
 * Builds one family's registry from its identifier list. Adding a preset is an
 * identifier in the contract, a stylesheet and two translation keys - never an
 * edit inside a component.
 */
export function createPresetRegistry(
  family: string,
  ids: readonly string[],
): Registry<PresetDefinition> {
  return createRegistry<PresetDefinition>(
    ids.map((id) => ({
      id,
      labelKey: `designSystem:presets.${family}.${id}.label`,
      descriptionKey: `designSystem:presets.${family}.${id}.description`,
    })),
  );
}
