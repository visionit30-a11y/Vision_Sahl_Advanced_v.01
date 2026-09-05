import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Icon } from '../../components/Icon/Icon';
import styles from './Breadcrumbs.module.css';

export interface Crumb {
  id: string;
  label: string;
  to?: string;
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  const { t } = useTranslation('navigation');

  if (items.length === 0) {
    return null;
  }

  return (
    <nav className={styles.breadcrumbs} aria-label={t('breadcrumb')}>
      <ol className={styles.list}>
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <Fragment key={item.id}>
              <li className={styles.item}>
                {item.to && !isLast ? (
                  <Link to={item.to} className={styles.link}>
                    {item.label}
                  </Link>
                ) : (
                  <span aria-current={isLast ? 'page' : undefined}>{item.label}</span>
                )}
              </li>
              {isLast ? null : (
                <li aria-hidden="true" className={styles.separator}>
                  <Icon name="chevronForward" size="sm" directional />
                </li>
              )}
            </Fragment>
          );
        })}
      </ol>
    </nav>
  );
}
