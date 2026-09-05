import type { ReactNode } from 'react';

import { errorId, hintId } from './fieldIds';
import styles from './FormField.module.css';

export interface FormFieldProps {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
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
