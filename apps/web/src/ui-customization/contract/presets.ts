/**
 * The presentation preset families.
 *
 * A family owns one variable prefix and nothing else. A preset file may declare
 * only its family's prefix, so an identity (which owns --color-* alone) and a
 * preset cannot collide: the identity decides colour, the preset decides form.
 * Guards enforce both halves of that sentence.
 */

/** The UiSettings keys these families fill. */
export type PresetSettingKey = 'buttonPreset' | 'alertPreset' | 'overlayPreset';

export const BUTTON_PRESET_IDS = [
  'compact-sharp',
  'institutional-standard',
  'balanced-roomy',
  'soft-rounded',
  'outlined-calm',
] as const;

export const ALERT_PRESET_IDS = [
  'tinted-standard',
  'bordered-quiet',
  'solid-emphatic',
  'minimal-inline',
  'dense-compact',
] as const;

export const OVERLAY_PRESET_IDS = [
  'institutional-standard',
  'compact-dense',
  'soft-elevated',
  'flat-bordered',
  'dim-focused',
] as const;

export type ButtonPresetId = (typeof BUTTON_PRESET_IDS)[number];
export type AlertPresetId = (typeof ALERT_PRESET_IDS)[number];
export type OverlayPresetId = (typeof OVERLAY_PRESET_IDS)[number];

export function isButtonPresetId(value: unknown): value is ButtonPresetId {
  return typeof value === 'string' && (BUTTON_PRESET_IDS as readonly string[]).includes(value);
}

export function isAlertPresetId(value: unknown): value is AlertPresetId {
  return typeof value === 'string' && (ALERT_PRESET_IDS as readonly string[]).includes(value);
}

export function isOverlayPresetId(value: unknown): value is OverlayPresetId {
  return typeof value === 'string' && (OVERLAY_PRESET_IDS as readonly string[]).includes(value);
}

/**
 * The button family. Sizes come from the shared control height scale and the
 * spacing scale; the three primary colour slots hold references to identity
 * tokens, which is what lets any preset work with any identity.
 */
export const BUTTON_PRESET_VARIABLES = [
  '--button-radius',
  '--button-height-md',
  '--button-height-sm',
  '--button-padding-inline-md',
  '--button-padding-inline-sm',
  '--button-icon-gap',
  '--button-font-weight',
  '--button-border-width',
  '--button-primary-bg',
  '--button-primary-bg-hover',
  '--button-primary-bg-active',
  '--button-primary-fg',
  '--button-primary-border',
  '--button-hover-elevation',
  '--button-pressed-translate-block',
  '--button-disabled-opacity',
] as const;

/**
 * The alert family, shared by InlineAlert and the status bar.
 *
 * The colour side is three mix ratios rather than three colour slots, and that
 * is not a style choice. A custom property is substituted on the element that
 * declares it, so a preset at :root cannot alias --tone-bg: the tone lives on
 * the message element, and the alias would resolve against nothing. Ratios do
 * resolve at :root, and a mix at 0% or 100% returns its endpoint exactly, so
 * the hand tuned and contrast checked tone tokens survive untouched.
 *
 *   solid-mix    100% draws the tone at full strength under inverse text
 *   surface-mix  100% replaces the tinted background with the plain surface
 *   bg-alpha       0% removes the background altogether
 *   accent-mix   100% paints the inline start edge in the tone at full strength
 *
 * --size-statusbar-height is deliberately NOT here: the reserved band is a
 * layout token, and a guard rejects any preset that tries to declare it.
 */
export const ALERT_PRESET_VARIABLES = [
  '--alert-padding-block',
  '--alert-padding-inline',
  '--alert-radius',
  '--alert-border-width',
  '--alert-accent-inline-start-width',
  '--alert-accent-mix',
  '--alert-solid-mix',
  '--alert-surface-mix',
  '--alert-bg-alpha',
  '--alert-icon-size',
  '--alert-icon-opacity',
  '--alert-font-size',
  '--alert-link-decoration',
] as const;

/**
 * The overlay family, shared by Modal and Menu.
 *
 * The identity owns the scrim's colour and the preset owns its depth: strength
 * scales the identity token down, and boost adds opaque darkness on top of it.
 * At strength 100% and boost 0% the result is the identity token exactly, so
 * the built-in preset reproduces the current dialog without approximating it.
 */
export const OVERLAY_PRESET_VARIABLES = [
  '--overlay-radius',
  '--overlay-shadow',
  '--overlay-border-width',
  '--overlay-border-color',
  '--overlay-padding-block',
  '--overlay-padding-inline',
  '--overlay-header-padding-block',
  '--overlay-footer-padding-block',
  '--overlay-scrim-strength',
  '--overlay-scrim-boost',
  '--overlay-menu-border-width',
  '--overlay-menu-radius',
  '--overlay-menu-padding-block',
  '--overlay-menu-padding-inline',
  '--overlay-menu-gap',
  '--overlay-selected-bg',
  '--overlay-selected-weight',
] as const;

export interface PresetFamily {
  /** The UiSettings key this family fills. */
  key: PresetSettingKey;
  /** The dataset property applyUiSettings writes on the document element. */
  attribute: string;
  /** The same thing as CSS sees it, which is what a preset file selects on. */
  dataAttribute: string;
  /** The directory under styles/presets/ holding this family's stylesheets. */
  directory: string;
  /** The only variable prefix a file in that directory may declare. */
  prefix: string;
  ids: readonly string[];
  variables: readonly string[];
  builtIn: string;
}

/**
 * One description of the families, so a guard, the preview and the engine all
 * read the same source. Adding a fourth family later is one entry here.
 */
export const PRESET_FAMILIES: readonly PresetFamily[] = [
  {
    key: 'buttonPreset',
    attribute: 'buttonPreset',
    dataAttribute: 'data-button-preset',
    directory: 'buttons',
    prefix: '--button-',
    ids: BUTTON_PRESET_IDS,
    variables: BUTTON_PRESET_VARIABLES,
    builtIn: 'institutional-standard',
  },
  {
    key: 'alertPreset',
    attribute: 'alertPreset',
    dataAttribute: 'data-alert-preset',
    directory: 'alerts',
    prefix: '--alert-',
    ids: ALERT_PRESET_IDS,
    variables: ALERT_PRESET_VARIABLES,
    builtIn: 'tinted-standard',
  },
  {
    key: 'overlayPreset',
    attribute: 'overlayPreset',
    dataAttribute: 'data-overlay-preset',
    directory: 'overlays',
    prefix: '--overlay-',
    ids: OVERLAY_PRESET_IDS,
    variables: OVERLAY_PRESET_VARIABLES,
    builtIn: 'institutional-standard',
  },
];
