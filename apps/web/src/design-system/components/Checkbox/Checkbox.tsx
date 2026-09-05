import { useId } from 'react';
import type { InputHTMLAttributes } from 'react';

import styles from './Checkbox.module.css';

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'type'> {
  label: string;
  hint?: string;
  id?: string;
}

export function Checkbox({ label, hint, id, className, ...rest }: CheckboxProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const describedById = hint ? `${fieldId}-hint` : undefined;

  return (
    <div className={[styles.wrapper, className].filter(Boolean).join(' ')}>
      <div className={styles.row}>
        <input
          id={fieldId}
          type="checkbox"
          className={styles.input}
          aria-describedby={describedById}
          {...rest}
        />
        <label className={styles.label} htmlFor={fieldId}>
          {label}
        </label>
      </div>
      {hint ? (
        <p className={styles.hint} id={describedById}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
