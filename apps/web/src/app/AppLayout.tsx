import { Fragment, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';

import { useUiCustomization } from '../ui-customization';
import { AppShell, Badge, Button, IconButton, InlineAlert, Menu } from '../design-system';
import { useActivityCenter } from '../activity-center/context';
import type { Crumb } from '../design-system';
import styles from './AppLayout.module.css';
import { useAppAuth } from './auth-state';
import { LanguageMenu } from './LanguageMenu';
import { NAV_SECTIONS } from './navigation';
import { FRONTEND_PERMISSIONS, usePermissionSnapshot } from './permission-state';

export function AppLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation(['navigation', 'designSystem', 'common']);
  const auth = useAppAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const activity = useActivityCenter();
  const { status, reload } = useUiCustomization();
  const permissions = usePermissionSnapshot();
  const visibleSections = NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => permissions.allows(item.requiredPermission)),
  })).filter((section) => section.items.length > 0);

  const tenantItems = auth.memberships.map((membership) => ({
    id: membership.id,
    label: membership.tenantName,
    selected: membership.id === auth.selectedMembershipId,
    onSelect: () => {
      if (membership.id !== auth.selectedMembershipId) {
        void auth.switchMembership(membership.id).catch(() => undefined);
      }
    },
  }));

  const home: Crumb = { id: 'home', label: t('navigation:items.home'), to: '/' };
  const currentLabel = location.pathname.startsWith('/design-system')
    ? t('navigation:items.designSystem')
    : location.pathname.startsWith('/documents')
      ? t('navigation:items.documents')
      : location.pathname.startsWith('/workflows/approvals')
        ? t('navigation:items.workflowApprovals')
        : location.pathname.startsWith('/workflows/requests')
          ? t('navigation:items.workflowRequests')
          : location.pathname.startsWith('/notifications')
            ? t('navigation:items.notifications')
            : location.pathname.startsWith('/tasks')
              ? t('navigation:items.tasks')
              : location.pathname.startsWith('/settings/notifications')
                ? t('navigation:items.notificationPreferences')
                : location.pathname.startsWith('/settings/users')
                  ? t('navigation:items.tenantUsers')
                  : location.pathname.startsWith('/settings/password')
                    ? t('navigation:items.changePassword')
                    : null;
  const breadcrumbs: Crumb[] = currentLabel ? [home, { id: 'current', label: currentLabel }] : [];

  return (
    <AppShell
      sections={visibleSections}
      breadcrumbs={breadcrumbs}
      headerActions={
        <>
          {permissions.allows(FRONTEND_PERMISSIONS.readWorkflowRequests) ? (
            <span className={styles.notificationButton}>
              <IconButton
                icon="bell"
                label={t('navigation:items.notifications')}
                tone="onHeader"
                onClick={() => navigate('/notifications')}
              />
              {activity.unreadCount > 0 ? (
                <span
                  className={styles.notificationBadge}
                  aria-label={t('navigation:unreadCount', { count: activity.unreadCount })}
                >
                  <Badge tone="danger">
                    {activity.unreadCount > 99 ? '99+' : activity.unreadCount}
                  </Badge>
                </span>
              ) : null}
            </span>
          ) : null}
          {auth.memberships.length > 0 ? (
            <Menu
              label={auth.selectedMembershipName || t('navigation:tenantSelector')}
              icon="layers"
              iconOnly
              onHeader
              items={tenantItems}
            />
          ) : null}
          <span className={styles.userSummary}>
            {t('common:login.signedInAs', { email: auth.user?.email })}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              void auth.logout().catch(() => undefined);
            }}
          >
            {t('common:login.logout', { defaultValue: 'Sign out' })}
          </Button>
          <LanguageMenu />
        </>
      }
    >
      {status !== 'ready' && (
        <InlineAlert
          tone={status === 'loading' || status === 'saving' ? 'info' : 'warning'}
          title={t(`designSystem:customization.state.${status}`)}
        >
          {t('designSystem:customization.temporaryDisplay')}
          {status !== 'loading' && status !== 'saving' ? (
            <Fragment>
              <span> </span>
              <Button
                onClick={() => {
                  void reload();
                }}
              >
                {t('designSystem:customization.retry')}
              </Button>
            </Fragment>
          ) : null}
        </InlineAlert>
      )}
      {children}
    </AppShell>
  );
}
