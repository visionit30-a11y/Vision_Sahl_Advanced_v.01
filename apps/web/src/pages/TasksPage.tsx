import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { activityCenterClient, type TaskRecord } from '../activity-center/client';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Select,
  TextField,
} from '../design-system';
import styles from './ActivityCenterPage.module.css';

const tone = { open: 'warning', overdue: 'danger', completed: 'success' } as const;

export function TasksPage() {
  const { t, i18n } = useTranslation('activityCenter');
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const load = useCallback(
    async (next = filters) => {
      setLoading(true);
      setError(false);
      try {
        setTasks(
          await activityCenterClient.tasks({
            bucket: next.bucket,
            requestType: next.requestType,
            createdFrom: next.createdFrom,
            createdTo: next.createdTo,
          }),
        );
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    },
    [filters],
  );
  useEffect(() => {
    void load();
  }, [load]);
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const next = Object.fromEntries(
      ['bucket', 'requestType', 'createdFrom', 'createdTo'].map((key) => [
        key,
        String(data.get(key) ?? ''),
      ]),
    );
    setFilters(next);
    void load(next);
  }
  let content: ReactNode = <LoadingState label={t('loading')} />;
  if (!loading && tasks.length === 0) content = <EmptyState title={t('tasks.empty')} />;
  if (!loading && tasks.length > 0)
    content = (
      <ul className={styles.list}>
        {tasks.map((task) => (
          <li key={task.id} className={styles.item} data-testid="activity-task">
            <div className={styles.header}>
              <strong>{task.title}</strong>
              <Badge tone={tone[task.bucket]}>{t(`tasks.${task.bucket}`)}</Badge>
            </div>
            <span className={styles.meta}>
              {task.request_type} ·{' '}
              {new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' }).format(
                new Date(task.due_at),
              )}
            </span>
            <div className={styles.actions}>
              <Button
                size="sm"
                onClick={() => navigate(`/workflows/approvals?request=${task.request_id}`)}
              >
                {t('actions.openRequest')}
              </Button>
            </div>
          </li>
        ))}
      </ul>
    );
  return (
    <>
      <PageHeader title={t('tasks.title')} description={t('tasks.description')} />
      <Card title={t('tasks.filters')}>
        <form className={styles.filters} onSubmit={apply}>
          <Select
            name="bucket"
            label={t('tasks.state')}
            options={[
              { value: '', label: t('tasks.all') },
              { value: 'open', label: t('tasks.open') },
              { value: 'completed', label: t('tasks.completed') },
              { value: 'overdue', label: t('tasks.overdue') },
            ]}
          />
          <TextField name="requestType" label={t('tasks.type')} />
          <TextField name="createdFrom" type="date" label={t('tasks.from')} />
          <TextField name="createdTo" type="date" label={t('tasks.to')} />
          <Button type="submit">{t('actions.filter')}</Button>
        </form>
      </Card>
      {error ? (
        <ErrorState
          title={t('errors.title')}
          description={t('errors.description')}
          action={<Button onClick={() => void load()}>{t('actions.retry')}</Button>}
        />
      ) : null}
      <Card title={t('tasks.list')}>{content}</Card>
    </>
  );
}
