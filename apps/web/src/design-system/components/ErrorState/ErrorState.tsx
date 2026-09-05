import type { ReactNode } from 'react';

import { Icon } from '../Icon/Icon';
import styles from './ErrorState.module.css';

export interface ErrorStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function ErrorState({ title, description, action }: ErrorStateProps) {
  return (
    <div className={styles.state} role="alert">
      <Icon name="alertCircle" className={styles.icon} />
      <p className={styles.title}>{title}</p>
      {description ? <p className={styles.description}>{description}</p> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
