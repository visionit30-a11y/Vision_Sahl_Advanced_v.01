import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { activityCenterClient, type NotificationPreferences } from '../activity-center/client';
import { Button, Card, Checkbox, ErrorState, LoadingState, PageHeader } from '../design-system';
import styles from './ActivityCenterPage.module.css';

const fields = [
  'approval_requested',
  'request_approved',
  'request_rejected',
  'request_returned',
  'overdue_tasks',
] as const;

export function NotificationPreferencesPage() {
  const { t } = useTranslation('activityCenter');
  const [value, setValue] = useState<NotificationPreferences | null>(null);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    void activityCenterClient.preferences().then(setValue, () => setError(true));
  }, []);
  async function save() {
    if (!value) return;
    setSaving(true);
    setError(false);
    try {
      setValue(await activityCenterClient.updatePreferences(value));
    } catch {
      setError(true);
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <PageHeader title={t('preferences.title')} description={t('preferences.description')} />
      {error ? (
        <ErrorState title={t('errors.title')} description={t('errors.description')} />
      ) : null}
      <Card title={t('preferences.inApp')}>
        {!value ? (
          <LoadingState label={t('loading')} />
        ) : (
          <div className={styles.preferences}>
            {fields.map((field) => (
              <Checkbox
                key={field}
                label={t(`preferences.fields.${field}`)}
                checked={value[field]}
                onChange={(event) => setValue({ ...value, [field]: event.target.checked })}
              />
            ))}
            <Checkbox
              label={t('preferences.mandatory')}
              checked
              disabled
              hint={t('preferences.mandatoryHint')}
            />
            <Button loading={saving} onClick={() => void save()}>
              {t('actions.save')}
            </Button>
          </div>
        )}
      </Card>
    </>
  );
}
