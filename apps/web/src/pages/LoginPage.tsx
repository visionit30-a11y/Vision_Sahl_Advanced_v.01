import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useAppAuth } from '../app/auth-state';
import { Button, Card, TextField } from '../design-system';

export function LoginPage() {
  const { t } = useTranslation('common');
  const navigate = useNavigate();
  const auth = useAppAuth();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (auth.user) {
      navigate('/', { replace: true });
    }
  }, [auth.user, navigate]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setFailed(false);
    try {
      await auth.login(String(data.get('email')), String(data.get('password')));
      form.reset();
      navigate('/');
    } catch {
      setFailed(true);
      form.reset();
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <h1>{t('login.title')}</h1>
      {failed && <p role="alert">{t('login.failure')}</p>}
      <form
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <TextField
          label={t('login.email')}
          name="email"
          type="email"
          autoComplete="username"
          required
          disabled={busy}
        />
        <TextField
          label={t('login.password')}
          name="password"
          type="password"
          autoComplete="current-password"
          required
          disabled={busy}
        />
        <Button type="submit" disabled={busy}>
          {t('login.submit')}
        </Button>
      </form>
    </Card>
  );
}
