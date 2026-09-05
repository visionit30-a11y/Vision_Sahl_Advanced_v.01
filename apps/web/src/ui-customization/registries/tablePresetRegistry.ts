import { TABLE_PRESET_IDS } from '../contract/presets';
import { createPresetRegistry } from './createPresetRegistry';

/** How a table is drawn: row density, header, grid lines, striping, emphasis. */
export const tablePresetRegistry = createPresetRegistry('table', TABLE_PRESET_IDS);
