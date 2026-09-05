import { useTranslation } from 'react-i18next';

import { Icon } from '../../components/Icon/Icon';
import type { IconName } from '../../components/Icon/Icon';
import { IconButton } from '../../components/IconButton/IconButton';
import { useStatusBar, useStatusMessage } from './StatusBarContext';
import type { StatusTone } from './statusBarTypes';
import styles from './StatusBar.module.css';

const TONE_ICON: Record<StatusTone, IconName> = {
  success: 'circleCheck',
  warning: 'alertTriangle',
  danger: 'alertCircle',
  info: 'info',
};

/**
 * The region always occupies the same height whether a message is present or
 * not, so showing or hiding a message never moves the content below it.
 */
export function StatusBarRegion() {
  const { t } = useTranslation(['status', 'common']);
  const message = useStatusMessage();
  const { clear } = useStatusBar();

  const dismissible = message?.dismissible ?? true;

  return (
    <div className={styles.region} aria-live="polite" aria-label={t('status:region')}>
      {message ? (
        <div className={[styles.bar, styles[message.tone]].join(' ')}>
          <Icon name={TONE_ICON[message.tone]} size="sm" className={styles.icon} />
          <p className={styles.text} title={t(message.messageKey, message.messageValues)}>
            {t(message.messageKey, message.messageValues)}
            {message.link ? (
              <a
                className={styles.link}
                href={message.link.href}
                target="_blank"
                rel="noopener noreferrer"
              >
                {message.link.label}
              </a>
            ) : null}
          </p>
          {message.undo ? (
            <button type="button" className={styles.undo} onClick={message.undo.onUndo}>
              {message.undo.label}
            </button>
          ) : null}
          {dismissible ? (
            <IconButton
              icon="close"
              size="sm"
              label={t('status:dismiss')}
              onClick={clear}
              className={styles.dismiss}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
