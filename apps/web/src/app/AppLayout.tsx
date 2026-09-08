import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router-dom';

import { useUiCustomization } from '../ui-customization';
import { AppShell, InlineAlert, Button } from '../design-system';
import type { Crumb } from '../design-system';
import { LanguageMenu } from './LanguageMenu';
import { NAV_SECTIONS } from './navigation';

export function AppLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation('navigation');
  const location = useLocation();
  const { status, reload } = useUiCustomization();

  const home: Crumb = { id: 'home', label: t('items.home'), to: '/' };
  const currentLabel = location.pathname.startsWith('/design-system')
    ? t('items.designSystem')
    : null;
  const breadcrumbs: Crumb[] = currentLabel ? [home, { id: 'current', label: currentLabel }] : [];

  return (
    <AppShell sections={NAV_SECTIONS} breadcrumbs={breadcrumbs} headerActions={<LanguageMenu />}>
      {status !== 'ready' && (
        <InlineAlert
          tone={status === 'loading' || status === 'saving' ? 'info' : 'warning'}
          title={t('designSystem:customization.state.' + status)}
        >
          {t('designSystem:customization.temporaryDisplay')}
          {status !== 'loading' && status !== 'saving' && (
            <Button
              onClick={() => {
                void reload();
              }}
            >
              {t('designSystem:customization.retry')}
            </Button>
          )}
        </InlineAlert>
      )}
      {children}
    </AppShell>
  );
}
