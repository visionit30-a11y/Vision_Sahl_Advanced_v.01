/**
 * The semantic token contract.
 *
 * Every theme must define exactly these names, and components may only read
 * names from this list. A guard checks both directions, so a theme that forgets
 * a token, or a component that invents one, fails the build rather than
 * degrading quietly at runtime.
 */
export const SEMANTIC_COLOR_TOKENS = [
  'bg-page',
  'bg-surface',
  'bg-subtle',
  'bg-hover',
  'border',
  'border-strong',
  'text-primary',
  'text-secondary',
  'text-muted',
  'text-inverse',
  'brand',
  'brand-hover',
  'brand-active',
  'brand-subtle',
  'brand-border',
  'on-brand',
  'secondary',
  'secondary-hover',
  'secondary-subtle',
  'on-secondary',
  'accent',
  'accent-subtle',
  'focus-ring',
  'link',
  'success',
  'success-fg',
  'success-bg',
  'success-border',
  'warning',
  'warning-fg',
  'warning-bg',
  'warning-border',
  'danger',
  'danger-fg',
  'danger-bg',
  'danger-border',
  'info',
  'info-fg',
  'info-bg',
  'info-border',
  'neutral',
  'neutral-fg',
  'neutral-bg',
  'neutral-border',
  'disabled-bg',
  'disabled-fg',
  'disabled-border',
  'selected-bg',
  'selected-fg',
  'selected-border',
  'overlay-scrim',
  'header-bg',
  'header-fg',
  'header-border',
  'nav-bg',
  'nav-fg',
  'nav-fg-muted',
  'nav-active-bg',
  'nav-active-fg',
  'nav-border',
] as const;

export type SemanticColorToken = (typeof SEMANTIC_COLOR_TOKENS)[number];

/**
 * Pairs that must meet WCAG AA. Text pairs need 4.5:1, interface pairs 3:1.
 * A theme that fails any of them is not shippable.
 */
export const CONTRAST_TEXT_PAIRS: readonly (readonly [SemanticColorToken, SemanticColorToken])[] = [
  ['text-primary', 'bg-page'],
  ['text-primary', 'bg-surface'],
  ['text-primary', 'bg-subtle'],
  ['text-secondary', 'bg-surface'],
  ['text-secondary', 'bg-page'],
  ['text-muted', 'bg-surface'],
  ['text-muted', 'bg-page'],
  ['on-brand', 'brand'],
  ['on-secondary', 'secondary'],
  ['link', 'bg-surface'],
  ['success-fg', 'success-bg'],
  ['warning-fg', 'warning-bg'],
  ['danger-fg', 'danger-bg'],
  ['info-fg', 'info-bg'],
  ['neutral-fg', 'neutral-bg'],
  ['header-fg', 'header-bg'],
  ['nav-fg', 'nav-bg'],
  ['nav-fg-muted', 'nav-bg'],
  ['nav-active-fg', 'nav-active-bg'],
  ['selected-fg', 'selected-bg'],

  // Pairs that exist because a presentation preset uses them.
  // solid-emphatic draws a tone at full strength under inverse text:
  ['text-inverse', 'success'],
  ['text-inverse', 'warning'],
  ['text-inverse', 'danger'],
  ['text-inverse', 'info'],
  ['text-inverse', 'neutral'],
  // outlined-calm turns the identity colour into the primary button's text,
  // on the surface at rest and on the subtle tint while hovered:
  ['brand', 'bg-surface'],
  ['brand', 'brand-subtle'],
];

export const CONTRAST_INTERFACE_PAIRS: readonly (readonly [
  SemanticColorToken,
  SemanticColorToken,
])[] = [
  ['focus-ring', 'bg-page'],
  ['focus-ring', 'bg-surface'],
  ['border-strong', 'bg-surface'],
  ['brand', 'bg-surface'],
  ['accent', 'bg-surface'],
  ['disabled-fg', 'disabled-bg'],
];

export const CONTRAST_MINIMUM_TEXT = 4.5;
export const CONTRAST_MINIMUM_INTERFACE = 3;
