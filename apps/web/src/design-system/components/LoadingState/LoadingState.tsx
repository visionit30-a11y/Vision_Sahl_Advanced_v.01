import { Spinner } from '../Spinner/Spinner';
import styles from './LoadingState.module.css';

export interface LoadingStateProps {
  label: string;
}

export function LoadingState({ label }: LoadingStateProps) {
  return (
    <div className={styles.state} role="status" aria-live="polite">
      <Spinner />
      <p className={styles.label}>{label}</p>
    </div>
  );
}
