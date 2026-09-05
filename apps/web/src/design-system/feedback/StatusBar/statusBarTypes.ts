import type { Tone } from '../../tones';

/**
 * Three separate concepts, kept separate on purpose.
 *
 *   Intent  - what happened in the domain. Nine values.
 *   Tone    - which colour family expresses it. Five values, derived.
 *   Preset  - how that family is drawn. Chosen by the customisation engine.
 *
 * A caller states the intent and nothing else. Tone is derived here, so there
 * is one way to say a thing rather than two that can disagree.
 */
export type StatusIntent =
  | 'success'
  | 'saved'
  | 'updated'
  | 'deleted'
  | 'cancelled'
  | 'blocked'
  | 'warning'
  | 'error'
  | 'info';

/** The status bar draws with the shared tone vocabulary. */
export type StatusTone = Tone;

/**
 * A deletion that went through is a success: the warning belonged before it,
 * not after. A refusal is not an error in the system but a refusal to the user,
 * and it reads in the same family. A cancellation is neither good nor bad news,
 * which is exactly why the neutral tone exists.
 */
const INTENT_TONE: Record<StatusIntent, StatusTone> = {
  success: 'success',
  saved: 'success',
  updated: 'success',
  deleted: 'success',
  cancelled: 'neutral',
  blocked: 'danger',
  warning: 'warning',
  error: 'danger',
  info: 'info',
};

export function statusIntentToTone(intent: StatusIntent): StatusTone {
  return INTENT_TONE[intent];
}

export interface StatusLink {
  /** The record reference shown in bold, for example JE-000123. */
  label: string;
  /** Opened in a separate tab so the current screen keeps its state. */
  href: string;
}

export interface StatusUndo {
  label: string;
  onUndo: () => void;
}

export interface StatusMessage {
  /**
   * What happened. Never a colour and never a preset: the engine decides how
   * this is drawn, and the caller decides only what it means.
   */
  intent: StatusIntent;
  /**
   * A translation key, never a rendered string. A message that is resolved at
   * call time freezes into one language and stops following the switcher.
   */
  messageKey: string;
  messageValues?: Record<string, string | number>;
  link?: StatusLink;
  /**
   * A capability of the message, not a state of it: whether the user can put
   * the thing back. Only supply it when the backend can genuinely reverse the
   * operation. No caller does yet; the engine is ready for the phase that
   * introduces one.
   */
  undo?: StatusUndo;
  dismissible?: boolean;
  /** null keeps the message until the user deals with it. */
  durationMs?: number | null;
}

export interface StatusBarActions {
  show: (message: StatusMessage) => void;
  clear: () => void;
}

/**
 * Outcomes the user asked for fade on their own. Anything that stops the user,
 * or warns them, waits until they deal with it.
 */
export function defaultDuration(intent: StatusIntent): number | null {
  const tone = statusIntentToTone(intent);
  return tone === 'warning' || tone === 'danger' ? null : 6000;
}
