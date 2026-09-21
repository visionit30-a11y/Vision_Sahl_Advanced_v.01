import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Button, Card, EmptyState, PageHeader } from '../design-system';
import { useAppAuth } from './auth-state';

interface ShellStatePageProps {
  titleKey: string;
  descriptionKey: string;
  action?: ReactNode;
}

function ShellStatePage({ titleKey, descriptionKey, action }: ShellStatePageProps) {
  const { t } = useTranslation(['common', 'navigation', 'home']);

  return (
    <Card>
      <PageHeader title={t(titleKey)} description={t(descriptionKey)} />
      <EmptyState title={t(titleKey)} description={t(descriptionKey)} action={action} />
    </Card>
  );
}

export function LoadingShellState() {
  return <ShellStatePage titleKey="home:stateLoading" descriptionKey="home:stateLoadingDesc" />;
}

export function UnauthenticatedShellState() {
  const { t } = useTranslation(['common', 'home']);

  return (
    <ShellStatePage
      titleKey="home:stateUnauthenticated"
      descriptionKey="home:stateUnauthenticatedDesc"
      action={
        <Button size="sm" onClick={() => window.location.assign('/login')}>
          {t('common:login.submit')}
        </Button>
      }
    />
  );
}

export function NoMembershipShellState() {
  const { t } = useTranslation('home');
  return (
    <ShellStatePage
      titleKey="home:stateNoMembership"
      descriptionKey="home:stateNoMembershipDesc"
      action={
        <Button size="sm" disabled>
          {t('home:stateNoMembershipAction')}
        </Button>
      }
    />
  );
}

export function TenantSelectionShellState() {
  const auth = useAppAuth();

  return (
    <ShellStatePage
      titleKey="home:stateTenantRequired"
      descriptionKey="home:stateTenantRequiredDesc"
      action={auth.memberships.map((membership) => (
        <Button
          key={membership.id}
          size="sm"
          onClick={() => {
            void auth.switchMembership(membership.id).catch(() => undefined);
          }}
        >
          {membership.tenantName}
        </Button>
      ))}
    />
  );
}

export function SessionExpiredShellState() {
  const { t } = useTranslation('common');

  return (
    <ShellStatePage
      titleKey="home:stateSessionExpired"
      descriptionKey="home:stateSessionExpiredDesc"
      action={
        <Button size="sm" onClick={() => window.location.assign('/login')}>
          {t('common:login.submit')}
        </Button>
      }
    />
  );
}

export function ForbiddenShellState() {
  const { t } = useTranslation('common');

  return (
    <ShellStatePage
      titleKey="home:stateForbidden"
      descriptionKey="home:stateForbiddenDesc"
      action={
        <Button size="sm" onClick={() => window.history.back()}>
          {t('common:actions.back')}
        </Button>
      }
    />
  );
}

export function ErrorShellState() {
  const { t } = useTranslation(['common', 'home']);
  const auth = useAppAuth();

  return (
    <ShellStatePage
      titleKey="home:stateError"
      descriptionKey="home:stateErrorDesc"
      action={
        <Button
          size="sm"
          onClick={() => {
            void auth.refresh();
          }}
        >
          {t('common:actions.retry')}
        </Button>
      }
    />
  );
}
