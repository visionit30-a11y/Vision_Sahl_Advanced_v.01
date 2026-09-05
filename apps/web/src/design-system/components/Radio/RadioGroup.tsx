import { useId } from 'react';

import styles from './RadioGroup.module.css';

export interface RadioOption {
  value: string;
  label: string;
  hint?: string;
}

export interface RadioGroupProps {
  legend: string;
  name?: string;
  options: RadioOption[];
  value: string;
  onValueChange: (value: string) => void;
  disabled?: boolean;
}

export function RadioGroup({
  legend,
  name,
  options,
  value,
  onValueChange,
  disabled = false,
}: RadioGroupProps) {
  const generatedName = useId();
  const groupName = name ?? generatedName;

  return (
    <fieldset className={styles.group}>
      <legend className={styles.legend}>{legend}</legend>
      {options.map((option) => {
        const optionId = `${groupName}-${option.value}`;
        return (
          <div className={styles.option} key={option.value}>
            <div className={styles.row}>
              <input
                id={optionId}
                className={styles.input}
                type="radio"
                name={groupName}
                value={option.value}
                checked={value === option.value}
                disabled={disabled}
                onChange={() => {
                  onValueChange(option.value);
                }}
                aria-describedby={option.hint ? `${optionId}-hint` : undefined}
              />
              <label className={styles.label} htmlFor={optionId}>
                {option.label}
              </label>
            </div>
            {option.hint ? (
              <p className={styles.hint} id={`${optionId}-hint`}>
                {option.hint}
              </p>
            ) : null}
          </div>
        );
      })}
    </fieldset>
  );
}
