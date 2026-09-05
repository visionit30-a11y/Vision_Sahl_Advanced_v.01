import { THEME_IDS } from '../contract/settings';
import type { ThemeId } from '../contract/settings';
import { createRegistry } from './createRegistry';
import type { RegistryEntry } from './createRegistry';

/**
 * Metadata only. Colour values live in styles/themes/<id>.css, which is what
 * lets a theme change repaint the page without React re-rendering anything.
 */
export interface ThemeDefinition extends RegistryEntry {
  id: ThemeId;
  labelKey: string;
  descriptionKey: string;
}

const definitions: readonly ThemeDefinition[] = THEME_IDS.map((id) => ({
  id,
  labelKey: `designSystem:themes.${id}.label`,
  descriptionKey: `designSystem:themes.${id}.description`,
}));

export const themeRegistry = createRegistry<ThemeDefinition>(definitions);
