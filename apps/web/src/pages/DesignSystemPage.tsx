import { useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { PALETTES, applyPalette, readStoredPalette } from '../app/palette';
import type { PaletteId } from '../app/palette';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorState,
  InlineAlert,
  LoadingState,
  Menu,
  Modal,
  PageHeader,
  RadioGroup,
  Select,
  Skeleton,
  TextArea,
  TextField,
  useStatusBar,
} from '../design-system';
import type { RadioOption } from '../design-system';
import styles from './DesignSystemPage.module.css';

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card title={title}>
      <div className={styles.section}>{children}</div>
    </Card>
  );
}

export function DesignSystemPage() {
  const { t } = useTranslation(['designSystem', 'common']);
  const { show, clear } = useStatusBar();
  const [palette, setPalette] = useState<PaletteId>(() => readStoredPalette());
  const [modalOpen, setModalOpen] = useState(false);

  const paletteOptions: RadioOption[] = PALETTES.map((id) => ({
    value: id,
    label: t(`designSystem:palette.options.${id}`),
    hint: t(`designSystem:palette.hints.${id}`),
  }));

  return (
    <>
      <PageHeader title={t('designSystem:title')} description={t('designSystem:description')} />

      <Card title={t('designSystem:palette.title')}>
        <div className={styles.section}>
          <p className={styles.note}>{t('designSystem:palette.description')}</p>
          <RadioGroup
            legend={t('designSystem:palette.label')}
            options={paletteOptions}
            value={palette}
            onValueChange={(value) => {
              const next = value as PaletteId;
              setPalette(next);
              applyPalette(next);
            }}
          />
        </div>
      </Card>

      <Section title={t('designSystem:sections.typography')}>
        <p className={styles.displayLg}>{t('common:app.name')}</p>
        <p className={styles.displayMd}>{t('common:app.tagline')}</p>
        <p>{t('designSystem:samples.cardBody')}</p>
        <p className={styles.note}>{t('designSystem:samples.recordNumber')} · 1234567890</p>
      </Section>

      <Section title={t('designSystem:sections.actions')}>
        <div className={styles.row}>
          <Button>{t('designSystem:samples.buttonPrimary')}</Button>
          <Button variant="secondary">{t('designSystem:samples.buttonSecondary')}</Button>
          <Button variant="ghost" iconStart="check">
            {t('designSystem:samples.buttonGhost')}
          </Button>
          <Button variant="danger">{t('designSystem:samples.buttonDanger')}</Button>
        </div>
        <div className={styles.row}>
          <Button size="sm">{t('designSystem:samples.buttonPrimary')}</Button>
          <Button size="sm" variant="secondary" disabled>
            {t('designSystem:samples.buttonSecondary')}
          </Button>
          <Button loading>{t('designSystem:samples.loading')}</Button>
          <Menu
            label={t('designSystem:samples.menuLabel')}
            items={[
              {
                id: 'edit',
                label: t('designSystem:samples.buttonGhost'),
                onSelect: () => undefined,
              },
              {
                id: 'delete',
                label: t('designSystem:samples.buttonDanger'),
                onSelect: () => undefined,
              },
            ]}
          />
        </div>
      </Section>

      <Section title={t('designSystem:sections.inputs')}>
        <div className={styles.grid}>
          <TextField
            label={t('designSystem:samples.fieldLabel')}
            hint={t('designSystem:samples.fieldHint')}
            placeholder={t('designSystem:samples.fieldPlaceholder')}
            required
          />
          <TextField
            label={t('designSystem:samples.fieldLabel')}
            error={t('designSystem:samples.fieldError')}
            defaultValue=""
          />
          <Select
            label={t('designSystem:samples.selectLabel')}
            placeholder={t('common:form.selectPlaceholder')}
            options={[
              { value: 'riyadh', label: t('designSystem:samples.cities.riyadh') },
              { value: 'jeddah', label: t('designSystem:samples.cities.jeddah') },
              { value: 'dammam', label: t('designSystem:samples.cities.dammam') },
            ]}
          />
          <TextArea label={t('designSystem:samples.textareaLabel')} />
        </div>
        <div className={styles.row}>
          <Checkbox label={t('designSystem:samples.checkboxLabel')} defaultChecked />
          <RadioGroup
            legend={t('designSystem:samples.radioLabel')}
            value="association"
            onValueChange={() => undefined}
            options={[
              { value: 'association', label: t('designSystem:samples.radioAssociation') },
              { value: 'foundation', label: t('designSystem:samples.radioFoundation') },
            ]}
          />
        </div>
      </Section>

      <Section title={t('designSystem:sections.display')}>
        <div className={styles.row}>
          <Badge tone="success">{t('designSystem:samples.badgeActive')}</Badge>
          <Badge tone="warning">{t('designSystem:samples.badgePending')}</Badge>
          <Badge tone="danger">{t('designSystem:samples.badgeStopped')}</Badge>
          <Badge tone="brand">{t('designSystem:samples.badgeActive')}</Badge>
          <Badge>{t('designSystem:samples.badgeActive')}</Badge>
        </div>
        <Skeleton />
      </Section>

      <Section title={t('designSystem:sections.feedback')}>
        <div className={styles.row}>
          <Button
            size="sm"
            onClick={() => {
              show({
                tone: 'success',
                messageKey: 'designSystem:samples.recordCreated',
                link: { label: t('designSystem:samples.recordNumber'), href: '/design-system' },
              });
            }}
          >
            {t('designSystem:showStatus.success')}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              show({ tone: 'warning', messageKey: 'designSystem:samples.warningMessage' });
            }}
          >
            {t('designSystem:showStatus.warning')}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              show({ tone: 'danger', messageKey: 'designSystem:samples.dangerMessage' });
            }}
          >
            {t('designSystem:showStatus.danger')}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              show({ tone: 'info', messageKey: 'designSystem:samples.infoMessage' });
            }}
          >
            {t('designSystem:showStatus.info')}
          </Button>
          <Button size="sm" variant="ghost" onClick={clear}>
            {t('designSystem:showStatus.clear')}
          </Button>
        </div>

        <InlineAlert tone="warning" title={t('designSystem:samples.badgePending')}>
          {t('designSystem:samples.warningMessage')}
        </InlineAlert>

        <div className={styles.grid}>
          <div className={styles.tile}>
            <LoadingState label={t('common:states.loading')} />
          </div>
          <div className={styles.tile}>
            <EmptyState
              title={t('common:states.emptyTitle')}
              description={t('common:states.emptyDescription')}
            />
          </div>
          <div className={styles.tile}>
            <ErrorState
              title={t('common:states.errorTitle')}
              description={t('common:states.errorDescription')}
              action={
                <Button size="sm" variant="secondary">
                  {t('common:actions.retry')}
                </Button>
              }
            />
          </div>
        </div>
      </Section>

      <Section title={t('designSystem:sections.overlay')}>
        <div className={styles.row}>
          <Button
            variant="secondary"
            onClick={() => {
              setModalOpen(true);
            }}
          >
            {t('designSystem:samples.modalTitle')}
          </Button>
        </div>
        <Modal
          open={modalOpen}
          title={t('designSystem:samples.modalTitle')}
          closeLabel={t('common:actions.close')}
          onClose={() => {
            setModalOpen(false);
          }}
          footer={
            <>
              <Button
                variant="secondary"
                onClick={() => {
                  setModalOpen(false);
                }}
              >
                {t('common:actions.cancel')}
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  setModalOpen(false);
                  show({ tone: 'danger', messageKey: 'designSystem:samples.dangerMessage' });
                }}
              >
                {t('common:actions.delete')}
              </Button>
            </>
          }
        >
          <p>{t('designSystem:samples.modalBody')}</p>
        </Modal>
      </Section>
    </>
  );
}
