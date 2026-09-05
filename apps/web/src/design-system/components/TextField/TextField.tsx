import { useId } from 'react';
import type { InputHTMLAttributes } from 'react';

import { FormField } from '../Field/FormField';
import { describedBy } from '../Field/fieldIds';
import control from '../Field/control.module.css';

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: string;
  hint?: string;
  error?: string;
  id?: string;
}

export function TextField({
  label,
  hint,
  error,
  required,
  id,
  className,
  ...rest
}: TextFieldProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const classes = [control.control, error ? control.invalid : '', className]
    .filter(Boolean)
    .join(' ');

  return (
    <FormField id={fieldId} label={label} hint={hint} error={error} required={required}>
      <input
        id={fieldId}
        className={classes}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, hint, error)}
        {...rest}
      />
    </FormField>
  );
}
