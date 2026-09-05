import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router-dom';

import { Icon } from '../../components/Icon/Icon';
import type { NavSection } from './navTypes';
import styles from './SideNav.module.css';

export interface SideNavProps {
  sections: NavSection[];
  open: boolean;
  onNavigate: () => void;
}

export function SideNav({ sections, open, onNavigate }: SideNavProps) {
  const { t } = useTranslation('navigation');

  return (
    <nav
      className={[styles.nav, open ? styles.open : ''].filter(Boolean).join(' ')}
      aria-label={t('mainNav')}
    >
      {sections.map((section) => (
        <div className={styles.section} key={section.id}>
          <p className={styles.sectionLabel}>{t(section.labelKey)}</p>
          <ul>
            {section.items.map((item) => (
              <li key={item.id}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    [styles.link, isActive ? styles.active : ''].filter(Boolean).join(' ')
                  }
                >
                  <Icon name={item.icon} size="sm" />
                  <span>{t(item.labelKey)}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
