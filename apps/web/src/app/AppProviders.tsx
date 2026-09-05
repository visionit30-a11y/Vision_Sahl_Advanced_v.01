import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { StatusBarProvider } from '../design-system';
import { directionOf } from '../i18n';
import { UiCustomizationProvider } from '../ui-customization';

export function AppProviders({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation();

  useEffect(() => {
    const root = document.documentElement;
    root.lang = i18n.language;
    root.dir = directionOf(i18n.language);
  }, [i18n.language]);

  return (
    <UiCustomizationProvider>
      <StatusBarProvider>{children}</StatusBarProvider>
    </UiCustomizationProvider>
  );
}
