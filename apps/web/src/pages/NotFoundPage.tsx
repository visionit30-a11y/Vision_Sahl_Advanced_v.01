import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Card, EmptyState } from '../design-system';

export function NotFoundPage() {
  const { t } = useTranslation(['common', 'navigation']);

  return (
    <Card>
      <EmptyState
        title={t('common:notFound.title')}
        description={t('common:notFound.description')}
        action={<Link to="/">{t('navigation:items.home')}</Link>}
      />
    </Card>
  );
}
