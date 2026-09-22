import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { useAppAuth } from '../app/auth-state';
import { FRONTEND_PERMISSIONS, usePermissionSnapshot } from '../app/permission-state';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Select,
  TextField,
} from '../design-system';
import {
  tenantAdministrationClient,
  type AccessEvent,
  type TenantRole,
  type TenantUser,
} from '../tenant-administration/client';
import styles from './TenantUsersPage.module.css';

export function TenantUsersPage() {
  const { t } = useTranslation('tenantAdministration');
  const auth = useAppAuth();
  const permissions = usePermissionSnapshot();
  const [users, setUsers] = useState<TenantUser[]>([]);
  const [roles, setRoles] = useState<TenantRole[]>([]);
  const [events, setEvents] = useState<AccessEvent[]>([]);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const canInvite = permissions.allows(FRONTEND_PERMISSIONS.inviteTenantUsers);
  const canManage = permissions.allows(FRONTEND_PERMISSIONS.manageTenantUsers);
  const canAssign = permissions.allows(FRONTEND_PERMISSIONS.manageTenantMemberships);
  const canAudit = permissions.allows(FRONTEND_PERMISSIONS.readAccessAudit);
  const canReadRoles = permissions.allows(FRONTEND_PERMISSIONS.readTenantRoles);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const [nextUsers, nextRoles, nextEvents] = await Promise.all([
        tenantAdministrationClient.users(),
        canReadRoles ? tenantAdministrationClient.roles() : Promise.resolve([]),
        canAudit ? tenantAdministrationClient.events() : Promise.resolve([]),
      ]);
      setUsers(nextUsers);
      setRoles(nextRoles.filter((role) => role.status === 'active'));
      setEvents(nextEvents);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [canAudit, canReadRoles]);

  useEffect(() => void load(), [load]);

  const filtered = useMemo(
    () =>
      users.filter(
        (user) =>
          (status === 'all' || user.membership_status === status) &&
          user.email.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
      ),
    [query, status, users],
  );
  const n = filtered.length;

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const email = String(new FormData(form).get('email') ?? '');
    setBusy(true);
    setError(false);
    try {
      await tenantAdministrationClient.invite(email);
      form.reset();
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(user: TenantUser) {
    setBusy(true);
    setError(false);
    try {
      await tenantAdministrationClient.setStatus(
        user.membership_id,
        user.membership_status === 'active' ? 'suspended' : 'active',
        user.membership_version,
      );
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  async function toggleRole(user: TenantUser, roleId: string) {
    if (!roleId) return;
    const assigned = user.role_ids.includes(roleId);
    setBusy(true);
    setError(false);
    try {
      if (assigned) await tenantAdministrationClient.removeRole(user.membership_id, roleId);
      else await tenantAdministrationClient.assignRole(user.membership_id, roleId);
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title={t('title')} description={t('description')} />
      {error ? (
        <ErrorState
          title={t('errors.title')}
          description={t('errors.description')}
          action={<Button onClick={() => void load()}>{t('actions.retry')}</Button>}
        />
      ) : null}
      <div className={styles.grid}>
        <Card title={t('directory.title')}>
          <div className={styles.filters}>
            <TextField
              label={t('directory.search')}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <Select
              label={t('directory.status')}
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              options={['all', 'pending', 'active', 'suspended'].map((value) => ({
                value,
                label: t(`status.${value}`),
              }))}
            />
          </div>
          {loading ? (
            <LoadingState label={t('loading')} />
          ) : n === 0 ? (
            <EmptyState title={t('directory.empty')} />
          ) : (
            <ul className={styles.list}>
              {filtered.map((user) => (
                <li key={user.membership_id} className={styles.user} data-testid="tenant-user">
                  <div>
                    <strong>{user.email}</strong>
                    <p>{user.role_titles.join(t('roles.separator')) || t('roles.none')}</p>
                  </div>
                  <Badge tone={user.membership_status === 'active' ? 'success' : 'warning'}>
                    {t(`status.${user.membership_status}`)}
                  </Badge>
                  <div className={styles.actions}>
                    {canManage ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={busy}
                        disabled={user.membership_id === auth.selectedMembershipId}
                        onClick={() => void changeStatus(user)}
                      >
                        {user.membership_status === 'active'
                          ? t('actions.suspend')
                          : t('actions.activate')}
                      </Button>
                    ) : null}
                    {canAssign && user.membership_id !== auth.selectedMembershipId ? (
                      <Select
                        label={t('roles.assign')}
                        placeholder={t('roles.choose')}
                        onChange={(event) => void toggleRole(user, event.target.value)}
                        options={roles.map((role) => ({
                          value: role.role_id,
                          label: `${user.role_ids.includes(role.role_id) ? '✓ ' : ''}${role.display_name}`,
                        }))}
                      />
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {canInvite ? (
          <Card title={t('invite.title')}>
            <form className={styles.form} onSubmit={(event) => void invite(event)}>
              <TextField name="email" type="email" label={t('invite.email')} required />
              <Button type="submit" loading={busy}>
                {t('invite.submit')}
              </Button>
            </form>
          </Card>
        ) : null}
        {canAudit ? (
          <Card title={t('audit.title')}>
            {events.length === 0 ? (
              <EmptyState title={t('audit.empty')} />
            ) : (
              <ul className={styles.audit}>
                {events.map((event) => (
                  <li key={event.id}>
                    <strong>{t(`events.${event.event_type}`)}</strong>
                    <span>{new Date(event.created_at).toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ) : null}
      </div>
    </>
  );
}
