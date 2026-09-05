import { useId } from 'react';
import type { SelectHTMLAttributes } from 'react';

import { FormField, describedBy } from '../Field/FormField';
import control from '../Field/control.module.css';
import styles from './Select.module.css';

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id' | 'children'> {
  label: string;
  options: SelectOption[];
  placeholder?: string;
  hint?: string;
  error?: string;
  id?: string;
}

export function Select({
  label,
  options,
  placeholder,
  hint,
  error,
  required,
  id,
  className,
  ...rest
}: SelectProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const classes = [control.control, styles.select, error ? control.invalid : '', className]
    .filter(Boolean)
    .join(' ');

  return (
    <FormField id={fieldId} label={label} hint={hint} error={error} required={required}>
      <select
        id={fieldId}
        className={classes}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, hint, error)}
        defaultValue={placeholder ? '' : undefined}
        {...rest}
      >
        {placeholder ? (
          <option value="" disabled>
            {placeholder}
          </option>
        ) : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FormField>
  );
}
