import {
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Ellipsis,
  ExternalLink,
  Globe,
  House,
  Inbox,
  Info,
  Layers,
  Menu,
  TriangleAlert,
  X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import styles from './Icon.module.css';

/*
 * Lucide is the platform icon set (ADR-0009). It is imported HERE ONLY: a guard
 * rejects the import anywhere else, so the whole application still depends on
 * this component's API rather than on a library. Names below are ours, not
 * Lucide's, which is why swapping the set again would touch this file alone.
 *
 * Every icon draws with currentColor, so colour comes from the semantic tokens
 * of whichever context the icon sits in.
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

const ICONS: Record<IconName, LucideIcon> = {
  menu: Menu,
  close: X,
  chevronDown: ChevronDown,
  chevronForward: ChevronRight,
  check: Check,
  circleCheck: CircleCheck,
  alertTriangle: TriangleAlert,
  alertCircle: CircleAlert,
  info: Info,
  home: House,
  layers: Layers,
  globe: Globe,
  moreHorizontal: Ellipsis,
  externalLink: ExternalLink,
  inbox: Inbox,
};

export interface IconProps {
  name: IconName;
  size?: 'sm' | 'md';
  /** Directional icons are mirrored automatically in right-to-left layouts. */
  directional?: boolean;
  className?: string;
}

export function Icon({ name, size = 'md', directional = false, className }: IconProps) {
  const Glyph = ICONS[name];
  const classes = [styles.icon, styles[size], directional ? styles.directional : '', className]
    .filter(Boolean)
    .join(' ');

  // Size comes from the stylesheet, not from the library's width and height
  // attributes, so one rule governs every icon in the interface.
  return <Glyph className={classes} strokeWidth={1.75} aria-hidden="true" focusable="false" />;
}
