import { ALERT_PRESET_IDS } from '../contract/presets';
import { createPresetRegistry } from './createPresetRegistry';

/**
 * How a tone is drawn, for inline alerts and the status bar alike. It decides
 * presentation only: which state a message reports is its intent, and that is a
 * separate concept entirely.
 */
export const alertPresetRegistry = createPresetRegistry('alert', ALERT_PRESET_IDS);
