import type { IconName } from './components/Icon/Icon';

/**
 * The visual severity families of the design system, shared by the status bar
 * and inline alerts so one vocabulary serves both.
 *
 * A tone says how something is coloured, never what happened: that is the
 * message's intent, and it is a separate concept.
 */
export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

export const TONE_ICON: Record<Tone, IconName> = {
  success: 'circleCheck',
  warning: 'alertTriangle',
  danger: 'alertCircle',
  info: 'info',
  neutral: 'info',
};
