import { useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

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
import {
  alertPresetRegistry,
  buttonPresetRegistry,
  overlayPresetRegistry,
  printPresetRegistry,
  tablePresetRegistry,
  themeRegistry,
  useUiCustomization,
} from '../ui-customization';
import type { EditableUiScope, UiSettings } from '../ui-customization';
import { PrintSpecimen } from './design-system/specimens/PrintSpecimen';
import { TableSpecimen } from './design-system/specimens/TableSpecimen';
import styles from './DesignSystemPage.module.css';

/** What a switcher needs from a registry, and nothing more. */
interface OptionSource {
  list: () => readonly { id: string; labelKey: string; descriptionKey: string }[];
}

/**
 * One row per setting. The list is data, so a fourth family later is an entry
 * here rather than another block of markup.
 */
const CUSTOMISABLE: readonly { key: keyof UiSettings; options: OptionSource }[] = [
  { key: 'theme', options: themeRegistry },
  { key: 'buttonPreset', options: buttonPresetRegistry },
  { key: 'alertPreset', options: alertPresetRegistry },
  { key: 'overlayPreset', options: overlayPresetRegistry },
  { key: 'tablePreset', options: tablePresetRegistry },
  { key: 'printPreset', options: printPresetRegistry },
];

const STATUS_INTENTS = [
  'saved',
  'updated',
  'deleted',
  'success',
  'cancelled',
  'blocked',
  'warning',
  'error',
  'info',
] as const;

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
  const { settings, origin, layers, canManage, setSetting, clearSetting } = useUiCustomization();
  const [scope, setScope] = useState<EditableUiScope>('platform');
  const [modalOpen, setModalOpen] = useState(false);

  const scopeOptions: RadioOption[] = [
    {
      value: 'platform',
      label: t('designSystem:customization.scopes.platform'),
      hint: t('designSystem:customization.scopeHints.platform'),
    },
    {
      value: 'tenant',
      label: t('designSystem:customization.scopes.tenant'),
      hint: t('designSystem:customization.scopeHints.tenant'),
    },
  ];

  // Built from the registries, so a sixth option anywhere needs no edit here.
  const optionsFor = (source: OptionSource): RadioOption[] =>
    source.list().map((entry) => ({
      value: entry.id,
      label: t(entry.labelKey),
      hint: t(entry.descriptionKey),
    }));

  const labelOf = (source: OptionSource, id: string): string => {
    const entry = source.list().find((candidate) => candidate.id === id);
    return entry ? t(entry.labelKey) : id;
  };

  return (
    <>
      <PageHeader title={t('designSystem:title')} description={t('designSystem:description')} />

      <Card title={t('designSystem:customization.title')}>
        <div className={styles.section}>
          <p className={styles.note}>{t('designSystem:customization.description')}</p>

          <RadioGroup
            legend={t('designSystem:customization.scopeLabel')}
            options={scopeOptions}
            value={scope}
            onValueChange={(value) => {
              setScope(value as EditableUiScope);
            }}
          />

          {canManage(scope) ? (
            <div className={styles.grid}>
              {CUSTOMISABLE.map((setting) => {
                const storedInScope = layers[scope]?.[setting.key];

                return (
                  <div key={setting.key} className={styles.setting}>
                    <div className={styles.row}>
                      <Badge tone="brand">{labelOf(setting.options, settings[setting.key])}</Badge>
                      <Badge>{t(`designSystem:customization.origin.${origin[setting.key]}`)}</Badge>
                    </div>
                    <RadioGroup
                      legend={t(`designSystem:customization.settings.${setting.key}`)}
                      options={optionsFor(setting.options)}
                      value={storedInScope ?? settings[setting.key]}
                      onValueChange={(value) => {
                        // The value comes from this setting's own registry, so
                        // it is a valid identifier for it by construction.
                        void setSetting(
                          scope,
                          setting.key,
                          value as UiSettings[typeof setting.key],
                        );
                      }}
                    />
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={storedInScope === undefined}
                      onClick={() => {
                        void clearSetting(scope, setting.key);
                      }}
                    >
                      {t('designSystem:customization.reset')}
                    </Button>
                    <p className={styles.note}>
                      {storedInScope === undefined
                        ? t('designSystem:customization.inheriting')
                        : t('designSystem:customization.customised')}
                    </p>
                  </div>
                );
              })}
            </div>
          ) : (
            <InlineAlert tone="info" title={t('designSystem:customization.notAllowedTitle')}>
              {t('designSystem:customization.notAllowed')}
            </InlineAlert>
          )}

          <InlineAlert tone="info" title={t('designSystem:customization.temporaryTitle')}>
            {t('designSystem:customization.temporary')}
          </InlineAlert>
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
        <p className={styles.note}>{t('designSystem:intents.description')}</p>
        <div className={styles.row}>
          {STATUS_INTENTS.map((intent) => (
            <Button
              key={intent}
              size="sm"
              variant="secondary"
              onClick={() => {
                show({
                  intent,
                  messageKey: `designSystem:intents.${intent}.message`,
                  link: { label: t('designSystem:samples.recordNumber'), href: '/design-system' },
                });
              }}
            >
              {t(`designSystem:intents.${intent}.label`)}
            </Button>
          ))}
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

      <Section title={t('designSystem:sections.tables')}>
        <p className={styles.note}>{t('designSystem:table.description')}</p>
        <TableSpecimen />
      </Section>

      <Section title={t('designSystem:sections.print')}>
        <InlineAlert tone="info" title={t('designSystem:print.simulationTitle')}>
          {t('designSystem:print.simulation')}
        </InlineAlert>
        <div className={styles.paper}>
          <PrintSpecimen />
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
                  show({ intent: 'deleted', messageKey: 'designSystem:samples.recordCreated' });
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
