import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { fetchApplicationHealth, fetchCacheHealth, fetchDatabaseHealth } from '../api/client';
import { Badge, Button, Card, PageHeader } from '../design-system';
import type { BadgeTone } from '../design-system';
import styles from './HomePage.module.css';

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
  const [rows, setRows] = useState<ServiceRow[]>(INITIAL_ROWS);
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

  return (
    <>
      <PageHeader title={t('home:welcome')} description={t('home:description')} />

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
