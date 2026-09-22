import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { activityCenterClient, type NotificationRecord } from '../activity-center/client';
import { useActivityCenter } from '../activity-center/context';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from '../design-system';
import styles from './ActivityCenterPage.module.css';

export function NotificationsPage() {
  const { t, i18n } = useTranslation('activityCenter');
  const navigate = useNavigate();
  const activity = useActivityCenter();
  const [items, setItems] = useState<NotificationRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setItems(await activityCenterClient.notifications());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function open(item: NotificationRecord) {
    if (!item.read_at) await activityCenterClient.markRead(item.id);
    await activity.reload();
    navigate(`/workflows/requests?request=${item.request_id}`);
  }
  async function markAll() {
    await activityCenterClient.markAllRead();
    await Promise.all([load(), activity.reload()]);
  }
  let content: ReactNode = <LoadingState label={t('loading')} />;
  if (!loading && items.length === 0) content = <EmptyState title={t('notifications.empty')} />;
  if (!loading && items.length > 0)
    content = (
      <ul className={styles.list}>
        {items.map((item) => (
          <li
            key={item.id}
            className={`${styles.item} ${item.read_at ? '' : styles.unread}`}
            data-testid="notification-item"
          >
            <div className={styles.header}>
              <strong>{t(`kinds.${item.kind}`)}</strong>
              <Badge tone={item.read_at ? 'neutral' : 'info'}>
                {t(item.read_at ? 'status.read' : 'status.unread')}
              </Badge>
            </div>
            <span>{item.title_snapshot}</span>
            <span className={styles.meta}>
              {new Intl.DateTimeFormat(i18n.language, {
                dateStyle: 'medium',
                timeStyle: 'short',
              }).format(new Date(item.created_at))}
            </span>
            <div className={styles.actions}>
              <Button size="sm" onClick={() => void open(item)}>
                {t('actions.openRequest')}
              </Button>
              {!item.read_at ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    void activityCenterClient
                      .markRead(item.id)
                      .then(() => Promise.all([load(), activity.reload()]))
                  }
                >
                  {t('actions.markRead')}
                </Button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    );
  return (
    <>
      <PageHeader title={t('notifications.title')} description={t('notifications.description')} />
      {error ? (
        <ErrorState
          title={t('errors.title')}
          description={t('errors.description')}
          action={<Button onClick={() => void load()}>{t('actions.retry')}</Button>}
        />
      ) : null}
      <Card
        title={t('notifications.all')}
        actions={
          <Button size="sm" variant="secondary" onClick={() => void markAll()}>
            {t('actions.markAllRead')}
          </Button>
        }
      >
        {content}
      </Card>
    </>
  );
}
