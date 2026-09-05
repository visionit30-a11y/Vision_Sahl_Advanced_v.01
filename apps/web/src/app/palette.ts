/**
 * Phase 1 only: lets the project owner compare the three identity proposals on
 * real components. Once a palette is approved it becomes the single set of
 * colour tokens and this switch is removed.
 */
export const PALETTES = ['a', 'b', 'c'] as const;

export type PaletteId = (typeof PALETTES)[number];

/** Approved by the project owner as the default platform theme. */
export const DEFAULT_PALETTE: PaletteId = 'c';

const STORAGE_KEY = 'sahl.palette';

function isPalette(value: string | null): value is PaletteId {
  return value === 'a' || value === 'b' || value === 'c';
}

export function readStoredPalette(): PaletteId {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isPalette(stored) ? stored : DEFAULT_PALETTE;
  } catch {
    return DEFAULT_PALETTE;
  }
}

export function applyPalette(palette: PaletteId): void {
  document.documentElement.dataset.palette = palette;
  try {
    window.localStorage.setItem(STORAGE_KEY, palette);
  } catch {
    // Storage may be unavailable; the palette still applies for this visit.
  }
}
