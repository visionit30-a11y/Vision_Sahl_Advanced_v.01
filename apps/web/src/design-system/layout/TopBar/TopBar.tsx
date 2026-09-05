import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { IconButton } from '../../components/IconButton/IconButton';
import styles from './TopBar.module.css';

export interface TopBarProps {
  navOpen: boolean;
  onToggleNav: () => void;
  actions?: ReactNode;
}

export function TopBar({ navOpen, onToggleNav, actions }: TopBarProps) {
  const { t } = useTranslation(['common', 'navigation']);

  return (
    <header className={styles.header}>
      <div className={styles.start}>
        <IconButton
          className={styles.navToggle}
          icon={navOpen ? 'close' : 'menu'}
          label={navOpen ? t('navigation:closeNav') : t('navigation:openNav')}
          tone="onHeader"
          onClick={onToggleNav}
          aria-expanded={navOpen}
        />
        <span className={styles.appName}>{t('common:app.name')}</span>
      </div>
      <div className={styles.end}>{actions}</div>
    </header>
  );
}
