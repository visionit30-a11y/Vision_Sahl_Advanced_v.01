import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { useAppAuth } from '../app/auth-state';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from '../design-system';
import { workflowClient, type DocumentCenterItem } from '../workflow/client';
import styles from './DocumentCenterPage.module.css';

function isPendingApproval(item: DocumentCenterItem): boolean {
  return item.relation === 'approver' && item.request_status === 'pending';
}

export function DocumentCenterPage() {
  const { t, i18n } = useTranslation('workflow');
  const navigate = useNavigate();
  const { selectedMembershipId } = useAppAuth();
  const [items, setItems] = useState<DocumentCenterItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    setItems([]);
    setLoading(true);
    setError(false);
    void workflowClient
      .documentCenter()
      .then((records) => {
        if (active) setItems(records);
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedMembershipId, reload]);

  async function download(item: DocumentCenterItem) {
    setError(false);
    try {
      const response = await workflowClient.downloadDocument(item.request_id, item.id);
      const url = URL.createObjectURL(await response.blob());
      const link = window.document.createElement('a');
      link.href = url;
      link.download = item.filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      setError(true);
    }
  }

  return (
    <>
      <PageHeader
        title={t('documents.centerTitle')}
        description={t('documents.centerDescription')}
      />
      {error ? (
        <ErrorState
          title={t('errors.title')}
          description={t('documents.error')}
          action={
            <Button onClick={() => setReload((value) => value + 1)}>{t('actions.retry')}</Button>
          }
        />
      ) : null}
      <Card title={t('documents.centerTitle')}>
        {loading ? <LoadingState label={t('loading')} /> : null}
        {!loading && !error && items.length === 0 ? (
          <EmptyState title={t('documents.centerEmpty')} />
        ) : null}
        {!loading && !error && items.length > 0 ? (
          <ul className={styles.list}>
            {items.map((item) => (
              <li key={item.id} className={styles.item} data-testid="document-center-item">
                <div className={styles.heading}>
                  <strong>{item.filename}</strong>
                  <Badge tone="neutral">{t(`status.${item.request_status}`)}</Badge>
                </div>
                <span>{t('documents.request', { title: item.request_title })}</span>
                <span className={styles.meta}>
                  {t('documents.size', { size: Math.ceil(item.byte_size / 1024) })} ·{' '}
                  {new Intl.DateTimeFormat(i18n.language, {
                    dateStyle: 'medium',
                    timeStyle: 'short',
                  }).format(new Date(item.created_at))}
                </span>
                <div className={styles.actions}>
                  <Button size="sm" variant="secondary" onClick={() => void download(item)}>
                    {t('documents.download')}
                  </Button>
                  {item.relation === 'requester' && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => navigate(`/workflows/requests?request=${item.request_id}`)}
                    >
                      {t('documents.openRequest')}
                    </Button>
                  )}
                  {isPendingApproval(item) && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => navigate('/workflows/approvals')}
                    >
                      {t('documents.openApproval')}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
    </>
  );
}
