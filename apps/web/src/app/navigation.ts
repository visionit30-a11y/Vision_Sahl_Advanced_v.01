import type { NavSection } from '../design-system';

/**
 * Only routes that actually exist appear here. A module joins the navigation
 * when its own phase delivers a real screen.
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    id: 'workspace',
    labelKey: 'sections.workspace',
    items: [
      { id: 'home', labelKey: 'items.home', icon: 'home', to: '/', end: true },
      {
        id: 'design-system',
        labelKey: 'items.designSystem',
        icon: 'layers',
        to: '/design-system',
      },
    ],
  },
];
