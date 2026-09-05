import { useTranslation } from 'react-i18next';

import { TableSpecimen } from './TableSpecimen';
import styles from './PrintSpecimen.module.css';

/*
 * A specimen of a printed document, not a report engine.
 *
 * It proves the --print-* contract: the header area, the title, the metadata
 * line, the separator rule, the table on paper, and the footer with its
 * signature and page number slots. Placement and measurement only - no
 * organisation name, no logo, no business field, no module content.
 *
 * The data-print-surface attribute is what the print stylesheet targets, so the
 * same values that draw this box draw the page. Same constraints as the table
 * specimen: no props, no state, no effect, no data.
 */
export function PrintSpecimen() {
  const { t } = useTranslation('designSystem');

  return (
    <div className={styles.surface} data-print-surface>
      <div className={styles.header}>
        <div className={styles.logoSlot} aria-hidden="true" />
        <p className={styles.headerText}>{t('print.organisationSlot')}</p>
      </div>

      <h3 className={styles.title}>{t('print.titleSlot')}</h3>
      <p className={styles.meta}>{t('print.metaSlot')}</p>
      <hr className={styles.rule} />

      <div className={styles.body}>
        <TableSpecimen />
      </div>

      <div className={styles.footer}>
        <p className={styles.signatureSlot}>{t('print.signatureSlot')}</p>
        <p className={styles.pageNumberSlot}>{t('print.pageNumberSlot')}</p>
      </div>
    </div>
  );
}
