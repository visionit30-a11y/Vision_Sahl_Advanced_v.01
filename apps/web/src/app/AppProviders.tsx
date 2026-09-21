import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { StatusBarProvider } from '../design-system';
import { directionOf } from '../i18n';
import { AppAuthProvider, useAppAuth } from './auth-state';
import { UiCustomizationProvider } from '../ui-customization';
import { FrontendPermissionProvider } from './permission-state';
import { workflowClient } from '../workflow/client';
import { ActivityCenterProvider } from '../activity-center/context';

export function AppProviders({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation();

  useEffect(() => {
    const root = document.documentElement;
    root.lang = i18n.language;
    root.dir = directionOf(i18n.language);
  }, [i18n.language]);

  return (
    <AppAuthProvider>
      <StatusBarProvider>
        <TenantScopedProviders>{children}</TenantScopedProviders>
      </StatusBarProvider>
    </AppAuthProvider>
  );
}

function TenantScopedProviders({ children }: { children: ReactNode }) {
  const auth = useAppAuth();

  // UI settings and permission presentation require a trusted tenant context.
  // Keeping them unmounted on /login also prevents anonymous auth probes from
  // racing the pre-auth login exchange on the shared client.
  if (auth.status !== 'authenticated') return children;

  return (
    <UiCustomizationProvider>
      <FrontendPermissionProvider loadWorkflowPermissions={workflowClient.permissions}>
        <ActivityCenterProvider>{children}</ActivityCenterProvider>
      </FrontendPermissionProvider>
    </UiCustomizationProvider>
  );
}
