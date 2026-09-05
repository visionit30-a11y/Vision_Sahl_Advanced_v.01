import type { ReactNode } from 'react';

import { Icon } from '../Icon/Icon';
import { TONE_ICON } from '../../tones';
import type { Tone } from '../../tones';
import styles from './InlineAlert.module.css';

/** Inline alerts draw with the shared tone vocabulary. */
export type AlertTone = Tone;

export interface InlineAlertProps {
  tone?: AlertTone;
  title?: string;
  children: ReactNode;
}

/** An alert bound to a specific area of a screen. Operation outcomes belong in the status bar. */
export function InlineAlert({ tone = 'info', title, children }: InlineAlertProps) {
  return (
    <div className={[styles.alert, styles[tone]].join(' ')} role="status">
      <Icon name={TONE_ICON[tone]} size="sm" className={styles.icon} />
      <div className={styles.content}>
        {title ? <p className={styles.title}>{title}</p> : null}
        <div className={styles.message}>{children}</div>
      </div>
    </div>
  );
}
