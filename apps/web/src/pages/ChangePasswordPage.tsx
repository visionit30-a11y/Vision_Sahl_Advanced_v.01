import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { authClient } from '../auth/client';
import { Button, Card, ErrorState, PageHeader, TextField } from '../design-system';
import styles from './TenantUsersPage.module.css';

export function ChangePasswordPage() {
  const { t } = useTranslation('tenantAdministration');
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(false);
    try {
      await authClient.changePassword(
        String(data.get('currentPassword') ?? ''),
        String(data.get('newPassword') ?? ''),
        String(data.get('confirmPassword') ?? ''),
      );
      navigate('/login', { replace: true });
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title={t('password.title')} description={t('password.description')} />
      {error ? <ErrorState title={t('errors.title')} description={t('password.error')} /> : null}
      <Card title={t('password.card')}>
        <form className={styles.form} onSubmit={(event) => void submit(event)}>
          <TextField
            type="password"
            name="currentPassword"
            label={t('password.current')}
            autoComplete="current-password"
            required
          />
          <TextField
            type="password"
            name="newPassword"
            label={t('password.new')}
            autoComplete="new-password"
            minLength={15}
            maxLength={128}
            required
          />
          <TextField
            type="password"
            name="confirmPassword"
            label={t('password.confirm')}
            autoComplete="new-password"
            minLength={15}
            maxLength={128}
            required
          />
          <Button type="submit" loading={busy}>
            {t('password.submit')}
          </Button>
        </form>
      </Card>
    </>
  );
}
