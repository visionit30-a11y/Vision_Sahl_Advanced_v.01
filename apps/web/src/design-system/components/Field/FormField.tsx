import type { ReactNode } from 'react';

import styles from './FormField.module.css';

export interface FormFieldProps {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
}

export function hintId(id: string): string {
  return `${id}-hint`;
}

export function errorId(id: string): string {
  return `${id}-error`;
}

export function describedBy(id: string, hint?: string, error?: string): string | undefined {
  const ids = [hint ? hintId(id) : null, error ? errorId(id) : null].filter(Boolean);
  return ids.length > 0 ? ids.join(' ') : undefined;
}

/**
 * The single field layout: label, control, short hint, inline error.
 * Field errors always stay next to the field; the status bar carries the
 * outcome of the operation, never a field validation message.
 */
export function FormField({ id, label, hint, error, required, children }: FormFieldProps) {
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
        {required ? (
          <span className={styles.required} aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      {children}
      {hint ? (
        <p className={styles.hint} id={hintId(id)}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className={styles.error} id={errorId(id)} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
