import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { fetchApplicationHealth, fetchCacheHealth, fetchDatabaseHealth } from '../api/client';
import { Badge, Button, Card, PageHeader } from '../design-system';
import type { BadgeTone } from '../design-system';
import styles from './HomePage.module.css';
import { useAppAuth } from '../app/auth-state';
import { activityCenterClient, type DashboardSummary } from '../activity-center/client';
import { FRONTEND_PERMISSIONS, usePermissionSnapshot } from '../app/permission-state';

type ServiceState = 'loading' | 'up' | 'down' | 'disabled' | 'error';

interface ServiceRow {
  id: 'application' | 'database' | 'cache';
  state: ServiceState;
  detail: string | null;
}

const INITIAL_ROWS: ServiceRow[] = [
  { id: 'application', state: 'loading', detail: null },
  { id: 'database', state: 'loading', detail: null },
  { id: 'cache', state: 'loading', detail: null },
];

const TONE: Record<ServiceState, BadgeTone> = {
  loading: 'neutral',
  up: 'success',
  down: 'danger',
  disabled: 'warning',
  error: 'danger',
};

export function HomePage() {
  const { t } = useTranslation(['home', 'common']);
  const auth = useAppAuth();
  const permissions = usePermissionSnapshot();
  const [rows, setRows] = useState<ServiceRow[]>(INITIAL_ROWS);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [checking, setChecking] = useState(false);

  const check = useCallback(async () => {
    setChecking(true);
    setRows(INITIAL_ROWS);

    const [application, database, cache] = await Promise.all([
      fetchApplicationHealth().then(
        (value): ServiceRow => ({
          id: 'application',
          state: 'up',
          detail: `${value.name} · ${value.version}`,
        }),
        (): ServiceRow => ({ id: 'application', state: 'error', detail: null }),
      ),
      fetchDatabaseHealth().then(
        (value): ServiceRow => ({ id: 'database', state: value.status, detail: value.detail }),
        (): ServiceRow => ({ id: 'database', state: 'error', detail: null }),
      ),
      fetchCacheHealth().then(
        (value): ServiceRow => ({ id: 'cache', state: value.status, detail: value.detail }),
        (): ServiceRow => ({ id: 'cache', state: 'error', detail: null }),
      ),
    ]);

    setRows([application, database, cache]);
    setChecking(false);
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  useEffect(() => {
    if (!permissions.allows(FRONTEND_PERMISSIONS.readWorkflowRequests)) return;
    void activityCenterClient.dashboard().then(setSummary, () => setSummary(null));
  }, [permissions]);

  return (
    <>
      <PageHeader title={t('home:welcome')} description={t('home:description')} />

      <Card title={t('home:workspaceContext')}>
        <dl className={styles.contextRows}>
          <div className={styles.contextRow}>
            <dt>{t('home:currentTenant')}</dt>
            <dd>{auth.selectedMembershipName}</dd>
          </div>
          <div className={styles.contextRow}>
            <dt>{t('home:currentUser')}</dt>
            <dd>{auth.user?.email}</dd>
          </div>
          <div className={styles.contextRow}>
            <dt>{t('home:activeSession')}</dt>
            <dd>
              <Badge tone="success">{t('home:serviceState.up')}</Badge>
            </dd>
          </div>
        </dl>
      </Card>

      {summary ? (
        <Card title={t('activityCenter:dashboard.title')}>
          <div className={styles.summaryMetrics}>
            <div>
              <strong>{summary.unread_notifications}</strong>
              <span>{t('activityCenter:dashboard.unread')}</span>
            </div>
            <div>
              <strong>{summary.pending_tasks}</strong>
              <span>{t('activityCenter:dashboard.pending')}</span>
            </div>
            <div>
              <strong>{summary.overdue_tasks}</strong>
              <span>{t('activityCenter:dashboard.overdue')}</span>
            </div>
          </div>
          <h3>{t('activityCenter:dashboard.recent')}</h3>
          {summary.recent_activity.length === 0 ? (
            <p>{t('activityCenter:dashboard.empty')}</p>
          ) : (
            <ul className={styles.rows}>
              {summary.recent_activity.map((item) => (
                <li className={styles.row} key={`${item.request_id}-${item.created_at}`}>
                  <span className={styles.name}>{item.title}</span>
                  <span className={styles.detail}>
                    {t(`workflow:events.${item.event_type}`)} ·{' '}
                    {t(`activityCenter:actors.${item.actor_kind}`)}
                  </span>
                  <Badge tone="neutral">{t(`workflow:status.${item.to_status}`)}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : null}

      <Card
        title={t('home:platformStatus')}
        actions={
          <Button
            variant="secondary"
            size="sm"
            loading={checking}
            onClick={() => {
              void check();
            }}
          >
            {t('common:actions.retry')}
          </Button>
        }
      >
        <ul className={styles.rows}>
          {rows.map((row) => (
            <li className={styles.row} key={row.id}>
              <span className={styles.name}>{t(`home:services.${row.id}`)}</span>
              <span className={styles.detail}>{row.detail}</span>
              <Badge tone={TONE[row.state]}>{t(`home:serviceState.${row.state}`)}</Badge>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
