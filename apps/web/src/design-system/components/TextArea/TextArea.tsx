import { useId } from 'react';
import type { TextareaHTMLAttributes } from 'react';

import { FormField } from '../Field/FormField';
import { describedBy } from '../Field/fieldIds';
import control from '../Field/control.module.css';
import styles from './TextArea.module.css';

export interface TextAreaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'> {
  label: string;
  hint?: string;
  error?: string;
  id?: string;
}

export function TextArea({
  label,
  hint,
  error,
  required,
  id,
  className,
  rows = 3,
  ...rest
}: TextAreaProps) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const classes = [control.control, styles.textArea, error ? control.invalid : '', className]
    .filter(Boolean)
    .join(' ');

  return (
    <FormField id={fieldId} label={label} hint={hint} error={error} required={required}>
      <textarea
        id={fieldId}
        rows={rows}
        className={classes}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, hint, error)}
        {...rest}
      />
    </FormField>
  );
}
