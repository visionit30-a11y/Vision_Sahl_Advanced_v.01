import type { ReactNode } from 'react';

import styles from './Card.module.css';

export interface CardProps {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Card({ title, actions, children, className }: CardProps) {
  return (
    <section className={[styles.card, className].filter(Boolean).join(' ')}>
      {title || actions ? (
        <header className={styles.header}>
          {title ? <h2 className={styles.title}>{title}</h2> : null}
          {actions ? <div className={styles.actions}>{actions}</div> : null}
        </header>
      ) : null}
      <div className={styles.body}>{children}</div>
    </section>
  );
}
