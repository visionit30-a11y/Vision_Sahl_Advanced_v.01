export type StatusTone = 'success' | 'warning' | 'danger' | 'info';

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
  tone: StatusTone;
  message: string;
  link?: StatusLink;
  /**
   * Only supply this when the backend can genuinely reverse the operation.
   * No caller does yet; the engine is ready for the phase that introduces one.
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

/** Success and information fade on their own; warnings and errors wait for the user. */
export function defaultDuration(tone: StatusTone): number | null {
  return tone === 'success' || tone === 'info' ? 6000 : null;
}
