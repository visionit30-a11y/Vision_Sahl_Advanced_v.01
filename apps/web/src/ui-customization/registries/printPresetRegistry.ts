import { PRINT_PRESET_IDS } from '../contract/presets';
import { createPresetRegistry } from './createPresetRegistry';

/** How a printed document is laid out: margins, type scale, rules, ink use. */
export const printPresetRegistry = createPresetRegistry('print', PRINT_PRESET_IDS);
