import { BUTTON_PRESET_IDS } from '../contract/presets';
import { createPresetRegistry } from './createPresetRegistry';

/** How a button is drawn: height, padding, radius, weight, emphasis. */
export const buttonPresetRegistry = createPresetRegistry('button', BUTTON_PRESET_IDS);
