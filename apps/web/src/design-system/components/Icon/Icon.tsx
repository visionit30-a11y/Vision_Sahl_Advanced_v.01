import type { ReactNode } from 'react';

import styles from './Icon.module.css';

/*
 * A single stroke-based icon style, coloured from design tokens through
 * currentColor. Phase 1 ships the minimum set the shell needs; the registry is
 * replaced by the approved open-licence icon set behind the same API.
 */
export type IconName =
  | 'menu'
  | 'close'
  | 'chevronDown'
  | 'chevronForward'
  | 'check'
  | 'circleCheck'
  | 'alertTriangle'
  | 'alertCircle'
  | 'info'
  | 'home'
  | 'layers'
  | 'globe'
  | 'moreHorizontal'
  | 'externalLink'
  | 'inbox';

const PATHS: Record<IconName, ReactNode> = {
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  chevronDown: <path d="M6 9.5l6 6 6-6" />,
  chevronForward: <path d="M9 5l7 7-7 7" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  circleCheck: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8.5 12.5l2.5 2.5 4.5-5" />
    </>
  ),
  alertTriangle: (
    <>
      <path d="M12 4.5L21 19H3L12 4.5z" />
      <path d="M12 10v4M12 16.5v.01" />
    </>
  ),
  alertCircle: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5M12 16v.01" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8v.01" />
    </>
  ),
  home: <path d="M4 10.5L12 4l8 6.5V20H4v-9.5zM10 20v-5h4v5" />,
  layers: <path d="M12 3.5l8 4.5-8 4.5-8-4.5 8-4.5zM4 13l8 4.5 8-4.5" />,
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3.5 12h17M12 3a15 15 0 010 18a15 15 0 010-18z" />
    </>
  ),
  moreHorizontal: (
    <>
      <circle cx="6" cy="12" r="1" />
      <circle cx="12" cy="12" r="1" />
      <circle cx="18" cy="12" r="1" />
    </>
  ),
  externalLink: (
    <path d="M14 5h5v5M19 5l-8 8M18 14v4a1 1 0 01-1 1H6a1 1 0 01-1-1V7a1 1 0 011-1h4" />
  ),
  inbox: <path d="M4 13h4l1.5 3h5L16 13h4M4 13l2-7h12l2 7v5a1 1 0 01-1 1H5a1 1 0 01-1-1v-5z" />,
};

export interface IconProps {
  name: IconName;
  size?: 'sm' | 'md';
  /** Directional icons are mirrored automatically in right-to-left layouts. */
  directional?: boolean;
  className?: string;
}

export function Icon({ name, size = 'md', directional = false, className }: IconProps) {
  const classes = [styles.icon, styles[size], directional ? styles.directional : '', className]
    .filter(Boolean)
    .join(' ');

  return (
    <svg
      className={classes}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
