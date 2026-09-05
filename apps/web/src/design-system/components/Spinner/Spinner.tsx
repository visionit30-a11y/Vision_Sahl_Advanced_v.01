import styles from './Spinner.module.css';

export interface SpinnerProps {
  size?: 'sm' | 'md';
  className?: string;
}

export function Spinner({ size = 'md', className }: SpinnerProps) {
  const classes = [styles.spinner, styles[size], className].filter(Boolean).join(' ');

  return (
    <svg className={classes} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle className={styles.track} cx="12" cy="12" r="9" fill="none" strokeWidth="2.5" />
      <circle className={styles.head} cx="12" cy="12" r="9" fill="none" strokeWidth="2.5" />
    </svg>
  );
}
