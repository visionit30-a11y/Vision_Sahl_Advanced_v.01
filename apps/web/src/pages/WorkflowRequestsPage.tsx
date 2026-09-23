import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Select,
  TextArea,
  TextField,
} from '../design-system';
import {
  workflowClient,
  type Approver,
  type WorkflowEvent,
  type WorkflowRequest,
} from '../workflow/client';
import styles from './WorkflowPage.module.css';
import { WorkflowDocuments } from '../workflow/WorkflowDocuments';
import { useAppAuth } from '../app/auth-state';

const statusTone = {
  draft: 'neutral',
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
  returned: 'warning',
} as const;

export function WorkflowRequestsPage() {
  const { t } = useTranslation('workflow');
  const auth = useAppAuth();
  const [searchParams] = useSearchParams();
  const focusedRequest = searchParams.get('request');
  const [requests, setRequests] = useState<WorkflowRequest[]>([]);
  const [approvers, setApprovers] = useState<Approver[]>([]);
  const [history, setHistory] = useState<Record<string, WorkflowEvent[]>>({});
  const [editing, setEditing] = useState<WorkflowRequest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [documentRequestId, setDocumentRequestId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const [nextRequests, nextApprovers] = await Promise.all([
        workflowClient.requests(),
        workflowClient.approvers(),
      ]);
      setRequests(nextRequests);
      setApprovers(nextApprovers);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(true);
    setError(false);
    const data = new FormData(form);
    const payload = {
      title: String(data.get('title') ?? ''),
      description: String(data.get('description') ?? ''),
      approver_membership_id: String(data.get('approver') ?? ''),
    };
    try {
      if (editing)
        await workflowClient.update(editing.id, { ...payload, expected_version: editing.version });
      else await workflowClient.create({ ...payload, request_type: 'general_request' });
      setEditing(null);
      form.reset();
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  async function submit(request: WorkflowRequest) {
    setBusy(true);
    setError(false);
    try {
      await workflowClient.submit(request.id, request.version);
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  async function toggleHistory(id: string) {
    if (history[id]) {
      setHistory((value) => {
        const next = { ...value };
        delete next[id];
        return next;
      });
      return;
    }
    try {
      setHistory((value) => ({ ...value, [id]: [] }));
      const events = await workflowClient.history(id);
      setHistory((value) => ({ ...value, [id]: events }));
    } catch {
      setError(true);
    }
  }

  let requestContent: ReactNode;
  if (loading) {
    requestContent = <LoadingState label={t('loading')} />;
  } else if (requests.length === 0) {
    requestContent = <EmptyState title={t('requests.empty')} />;
  } else {
    requestContent = (
      <ul className={styles.list}>
        {requests.map((request) => {
          const events = history[request.id];
          return (
            <li
              className={styles.request}
              key={request.id}
              data-testid="workflow-request"
              data-request-id={request.id}
              aria-current={focusedRequest === request.id ? 'true' : undefined}
            >
              <div className={styles.requestHeader}>
                <strong>{request.title}</strong>
                <Badge tone={statusTone[request.status]}>{t(`status.${request.status}`)}</Badge>
              </div>
              <span className={styles.meta}>
                {request.request_type} · {t('version', { version: request.version })}
              </span>
              <p>{request.description}</p>
              <div className={styles.actions}>
                {['draft', 'returned'].includes(request.status) ? (
                  <>
                    <Button size="sm" variant="secondary" onClick={() => setEditing(request)}>
                      {t('actions.edit')}
                    </Button>
                    <Button size="sm" loading={busy} onClick={() => void submit(request)}>
                      {t('actions.submit')}
                    </Button>
                  </>
                ) : null}
                <Button size="sm" variant="ghost" onClick={() => void toggleHistory(request.id)}>
                  {t('actions.history')}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setDocumentRequestId(documentRequestId === request.id ? null : request.id)
                  }
                >
                  {t('documents.title')}
                </Button>
              </div>
              {documentRequestId === request.id ? (
                <WorkflowDocuments
                  requestId={request.id}
                  mayUpload={
                    request.requester_membership_id === auth.selectedMembershipId &&
                    ['draft', 'returned'].includes(request.status)
                  }
                />
              ) : null}
              {events ? (
                <div className={styles.history} data-testid="workflow-history">
                  {events.map((item) => (
                    <p key={item.id}>
                      <strong>{t(`events.${item.event_type}`)}</strong>
                      {` · ${t(`actors.${item.actor_kind}`)} · ${t(`status.${item.from_status ?? item.to_status}`)} → ${t(`status.${item.to_status}`)}`}
                      {item.note ? ` — ${item.note}` : ''}
                      <span className={styles.meta}>
                        {' '}
                        · {new Date(item.created_at).toLocaleString()}
                      </span>
                    </p>
                  ))}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <>
      <PageHeader title={t('requests.title')} description={t('requests.description')} />
      {error ? (
        <ErrorState
          title={t('errors.title')}
          description={t('errors.description')}
          action={<Button onClick={() => void load()}>{t('actions.retry')}</Button>}
        />
      ) : null}
      <div className={styles.grid}>
        <Card title={editing ? t('form.edit') : t('form.create')}>
          <form
            className={styles.form}
            onSubmit={(event) => void save(event)}
            key={editing?.id ?? 'new'}
          >
            <TextField
              name="title"
              label={t('form.title')}
              required
              defaultValue={editing?.title}
              maxLength={160}
            />
            <TextArea
              name="description"
              label={t('form.description')}
              required
              defaultValue={editing?.description}
              maxLength={2000}
            />
            <Select
              name="approver"
              label={t('form.approver')}
              required
              defaultValue={editing?.approver_membership_id ?? ''}
              placeholder={t('form.chooseApprover')}
              options={approvers.map((item) => ({
                value: item.membership_id,
                label: item.display_name,
              }))}
            />
            <div className={styles.actions}>
              <Button type="submit" loading={busy}>
                {t('actions.save')}
              </Button>
              {editing ? (
                <Button type="button" variant="secondary" onClick={() => setEditing(null)}>
                  {t('actions.cancel')}
                </Button>
              ) : null}
            </div>
          </form>
        </Card>
        <Card title={t('requests.list')}>{requestContent}</Card>
      </div>
    </>
  );
}
