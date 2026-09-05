import { useTranslation } from 'react-i18next';

import styles from './TableSpecimen.module.css';

/*
 * A specimen, not a table component.
 *
 * It exists to prove the --table-* contract on screen and to give the guards
 * something real to check. It takes no props, holds no state, runs no effect
 * and fetches nothing, and it is not exported from the design system, so no
 * business screen can reach it. It disappears when the table engine arrives -
 * and that engine will read this same contract rather than invent a third
 * shape.
 *
 * Every value below is invented placeholder text from the translation layer.
 */
const ROWS = ['one', 'two', 'three', 'four', 'five'] as const;

/** The third row stands in for a selected record. */
const SELECTED_ROW = 'three';

export function TableSpecimen() {
  const { t } = useTranslation('designSystem');

  return (
    <div className={styles.wrapper}>
      <table className={styles.table}>
        <caption className={styles.caption}>{t('table.caption')}</caption>
        <thead>
          <tr>
            <th scope="col" className={styles.headerCell}>
              {t('table.columns.item')}
            </th>
            <th scope="col" className={styles.headerCell}>
              {t('table.columns.status')}
            </th>
            <th scope="col" className={styles.headerCell}>
              {t('table.columns.date')}
            </th>
            <th scope="col" className={[styles.headerCell, styles.numeric].join(' ')}>
              {t('table.columns.amount')}
            </th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => (
            <tr
              key={row}
              className={[styles.row, row === SELECTED_ROW ? styles.selected : '']
                .filter(Boolean)
                .join(' ')}
            >
              <td className={styles.cell}>{t(`table.rows.${row}.item`)}</td>
              <td className={styles.cell}>{t(`table.rows.${row}.status`)}</td>
              <td className={styles.cell}>{t(`table.rows.${row}.date`)}</td>
              <td className={[styles.cell, styles.numeric].join(' ')}>
                {t(`table.rows.${row}.amount`)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className={styles.totalRow}>
            <td className={styles.totalCell} colSpan={3}>
              {t('table.total')}
            </td>
            <td className={[styles.totalCell, styles.numeric].join(' ')}>
              {t('table.totalAmount')}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
