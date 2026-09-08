import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { authClient } from '../auth/client';
import type { AuthenticatedUser, MembershipSummary } from '../auth/client';
import { Button, Card, TextField } from '../design-system';

export function LoginPage() {
  const { t } = useTranslation('common');
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [memberships, setMemberships] = useState<MembershipSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    const unsubscribe = authClient.subscribe(() => {
      setUser(null);
      setMemberships([]);
    });
    void authClient
      .me()
      .then(async (current) => {
        await authClient.bootstrapCsrf();
        const available = await authClient.memberships();
        if (active) {
          setUser(current);
          setMemberships(available);
        }
      })
      .catch(() => {
        /* An anonymous visitor sees the login form. */
      });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setFailed(false);
    try {
      const current = await authClient.login(
        String(data.get('email')),
        String(data.get('password')),
      );
      form.reset();
      const available = await authClient.memberships();
      setUser(current);
      setMemberships(available);
    } catch {
      setFailed(true);
      form.reset();
    } finally {
      setBusy(false);
    }
  }
  async function select(id: string) {
    setBusy(true);
    setFailed(false);
    try {
      const current = await authClient.switchTenant(id);
      const available = await authClient.memberships();
      setUser(current);
      setMemberships(available);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <h1>{t('login.title')}</h1>
      {failed && <p role="alert">{t('login.failure')}</p>}
      {!user ? (
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
      ) : (
        <div>
          <p role="status">{t(user.selectedMembershipId ? 'login.ready' : 'login.selectTenant')}</p>
          {memberships.map((membership) => (
            <Button
              key={membership.id}
              disabled={busy}
              onClick={() => {
                void select(membership.id);
              }}
            >
              {membership.tenantName}
            </Button>
          ))}
          <Button
            disabled={busy}
            onClick={() => {
              setBusy(true);
              void authClient
                .logout()
                .catch(() => setFailed(true))
                .finally(() => setBusy(false));
            }}
          >
            {t('login.logout')}
          </Button>
        </div>
      )}
    </Card>
  );
}
