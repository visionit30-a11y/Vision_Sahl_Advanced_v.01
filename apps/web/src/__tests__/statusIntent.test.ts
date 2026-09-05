import { describe, expect, it } from 'vitest';

import { statusIntentToTone } from '../design-system';
import { defaultDuration } from '../design-system/feedback/StatusBar/statusBarTypes';
import type { StatusIntent } from '../design-system';

const INTENTS: StatusIntent[] = [
  'success',
  'saved',
  'updated',
  'deleted',
  'cancelled',
  'blocked',
  'warning',
  'error',
  'info',
];

describe('status intent', () => {
  it('maps every intent to a tone', () => {
    expect(INTENTS.map((intent) => [intent, statusIntentToTone(intent)])).toEqual([
      ['success', 'success'],
      ['saved', 'success'],
      ['updated', 'success'],
      ['deleted', 'success'],
      ['cancelled', 'neutral'],
      ['blocked', 'danger'],
      ['warning', 'warning'],
      ['error', 'danger'],
      ['info', 'info'],
    ]);
  });

  it('treats a completed deletion as an outcome, not a warning', () => {
    expect(statusIntentToTone('deleted')).toBe('success');
  });

  it('gives a cancellation its own tone instead of borrowing information', () => {
    expect(statusIntentToTone('cancelled')).toBe('neutral');
  });

  it('keeps a refusal in the same family as an error', () => {
    expect(statusIntentToTone('blocked')).toBe(statusIntentToTone('error'));
  });

  it('lets outcomes fade and makes anything that stops the user wait', () => {
    expect(defaultDuration('saved')).toBe(6000);
    expect(defaultDuration('cancelled')).toBe(6000);
    expect(defaultDuration('info')).toBe(6000);
    expect(defaultDuration('warning')).toBeNull();
    expect(defaultDuration('error')).toBeNull();
    expect(defaultDuration('blocked')).toBeNull();
  });
});
