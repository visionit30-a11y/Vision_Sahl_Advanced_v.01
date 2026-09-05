import type { ButtonHTMLAttributes } from 'react';

import { Icon } from '../Icon/Icon';
import type { IconName } from '../Icon/Icon';
import styles from './IconButton.module.css';

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  /** Required: an icon-only control must still expose an accessible name. */
  label: string;
  size?: 'sm' | 'md';
  tone?: 'default' | 'onHeader';
  directional?: boolean;
}

export function IconButton({
  icon,
  label,
  size = 'md',
  tone = 'default',
  directional = false,
  className,
  type = 'button',
  ...rest
}: IconButtonProps) {
  const classes = [styles.iconButton, styles[size], styles[tone], className]
    .filter(Boolean)
    .join(' ');

  return (
    <button type={type} className={classes} aria-label={label} title={label} {...rest}>
      <Icon name={icon} size={size} directional={directional} />
    </button>
  );
}
