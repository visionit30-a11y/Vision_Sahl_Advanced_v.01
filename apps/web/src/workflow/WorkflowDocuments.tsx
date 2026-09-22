import { useCallback, useEffect, useState, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../design-system';
import { workflowClient, type WorkflowDocument } from './client';
import styles from './WorkflowDocuments.module.css';

export function WorkflowDocuments({
  requestId,
  mayUpload,
}: {
  requestId: string;
  mayUpload: boolean;
}) {
  const { t } = useTranslation('workflow');
  const [documents, setDocuments] = useState<WorkflowDocument[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setDocuments(await workflowClient.documents(requestId));
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [requestId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function upload() {
    if (!file || busy) return;
    setBusy(true);
    setError(false);
    try {
      await workflowClient.uploadDocument(requestId, file);
      setFile(null);
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  async function download(document: WorkflowDocument) {
    setError(false);
    try {
      const response = await workflowClient.downloadDocument(requestId, document.id);
      const url = URL.createObjectURL(await response.blob());
      const link = window.document.createElement('a');
      link.href = url;
      link.download = document.filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      setError(true);
    }
  }

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setError(false);
  }

  return (
    <section className={styles.documents} aria-label={t('documents.title')}>
      {loading ? <p role="status">{t('loading')}</p> : null}
      {error ? (
        <div role="alert" className={styles.error}>
          <span>{t('documents.error')}</span>
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            {t('documents.retry')}
          </Button>
        </div>
      ) : null}
      {!loading && documents.length === 0 ? <p>{t('documents.empty')}</p> : null}
      <ul className={styles.list}>
        {documents.map((document) => (
          <li key={document.id}>
            <span>{document.filename}</span>
            <span>{t('documents.size', { size: Math.ceil(document.byte_size / 1024) })}</span>
            <Button size="sm" variant="secondary" onClick={() => void download(document)}>
              {t('documents.download')}
            </Button>
          </li>
        ))}
      </ul>
      {mayUpload ? (
        <div className={styles.upload}>
          <label htmlFor={`document-${requestId}`}>{t('documents.choose')}</label>
          <input
            id={`document-${requestId}`}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
            onChange={chooseFile}
          />
          <Button size="sm" disabled={!file || busy} onClick={() => void upload()}>
            {busy ? t('documents.uploading') : t('documents.upload')}
          </Button>
          <small>{t('documents.limit')}</small>
        </div>
      ) : null}
    </section>
  );
}
