import { OVERLAY_PRESET_IDS } from '../contract/presets';
import { createPresetRegistry } from './createPresetRegistry';

/** How dialogs and menus are drawn: radius, shadow, density, scrim strength. */
export const overlayPresetRegistry = createPresetRegistry('overlay', OVERLAY_PRESET_IDS);
