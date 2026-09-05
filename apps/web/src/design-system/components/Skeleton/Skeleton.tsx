import styles from './Skeleton.module.css';

export interface SkeletonProps {
  lines?: number;
}

export function Skeleton({ lines = 3 }: SkeletonProps) {
  return (
    <div className={styles.skeleton} aria-hidden="true">
      {Array.from({ length: lines }, (_, index) => (
        <span className={styles.line} key={index} />
      ))}
    </div>
  );
}
