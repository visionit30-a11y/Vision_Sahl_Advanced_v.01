import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  TextArea,
} from '../design-system';
import { workflowClient, type ApprovalTask, type WorkflowDecision } from '../workflow/client';
import styles from './WorkflowPage.module.css';

export function WorkflowApprovalsPage() {
  const { t } = useTranslation('workflow');
  const [tasks, setTasks] = useState<ApprovalTask[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setTasks(await workflowClient.inbox());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function decide(task: ApprovalTask, decision: WorkflowDecision) {
    setError(false);
    try {
      await workflowClient.decide(task.id, decision, task.version, notes[task.id] ?? '');
      await load();
    } catch {
      setError(true);
    }
  }
  let inboxContent: ReactNode;
  if (loading) {
    inboxContent = <LoadingState label={t('loading')} />;
  } else if (tasks.length === 0) {
    inboxContent = <EmptyState title={t('approvals.empty')} />;
  } else {
    inboxContent = (
      <ul className={styles.list}>
        {tasks.map((task) => (
          <li className={styles.request} key={task.id} data-testid="approval-task">
            <div className={styles.requestHeader}>
              <strong>{task.title}</strong>
              <span className={styles.meta}>{task.request_type}</span>
            </div>
            <TextArea
              label={t('approvals.note')}
              value={notes[task.id] ?? ''}
              onChange={(event) =>
                setNotes((value) => ({ ...value, [task.id]: event.target.value }))
              }
              maxLength={1000}
            />
            <div className={styles.actions}>
              <Button size="sm" onClick={() => void decide(task, 'approve')}>
                {t('actions.approve')}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => void decide(task, 'return')}>
                {t('actions.return')}
              </Button>
              <Button size="sm" variant="danger" onClick={() => void decide(task, 'reject')}>
                {t('actions.reject')}
              </Button>
            </div>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <>
      <PageHeader title={t('approvals.title')} description={t('approvals.description')} />
      {error ? (
        <ErrorState
          title={t('errors.title')}
          description={t('errors.description')}
          action={<Button onClick={() => void load()}>{t('actions.retry')}</Button>}
        />
      ) : null}
      <Card title={t('approvals.inbox')}>{inboxContent}</Card>
    </>
  );
}
