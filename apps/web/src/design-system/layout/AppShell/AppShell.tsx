import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { StatusBarRegion } from '../../feedback/StatusBar/StatusBarRegion';
import { Breadcrumbs } from '../Breadcrumbs/Breadcrumbs';
import type { Crumb } from '../Breadcrumbs/Breadcrumbs';
import { SideNav } from '../SideNav/SideNav';
import type { NavSection } from '../SideNav/navTypes';
import { TopBar } from '../TopBar/TopBar';
import styles from './AppShell.module.css';

export interface AppShellProps {
  sections: NavSection[];
  breadcrumbs?: Crumb[];
  headerActions?: ReactNode;
  children: ReactNode;
}

export function AppShell({ sections, breadcrumbs, headerActions, children }: AppShellProps) {
  const { t } = useTranslation('common');
  const [navOpen, setNavOpen] = useState(false);

  const closeNav = useCallback(() => {
    setNavOpen(false);
  }, []);

  useEffect(() => {
    if (!navOpen) {
      return;
    }

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeNav();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [navOpen, closeNav]);

  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#main-content">
        {t('skipToContent')}
      </a>

      <TopBar
        navOpen={navOpen}
        onToggleNav={() => {
          setNavOpen((value) => !value);
        }}
        actions={headerActions}
      />

      <div className={styles.body}>
        <SideNav sections={sections} open={navOpen} onNavigate={closeNav} />
        {navOpen ? <div className={styles.scrim} onClick={closeNav} aria-hidden="true" /> : null}

        <div className={styles.content}>
          <StatusBarRegion />
          <main className={styles.main} id="main-content" tabIndex={-1}>
            {breadcrumbs && breadcrumbs.length > 0 ? <Breadcrumbs items={breadcrumbs} /> : null}
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
