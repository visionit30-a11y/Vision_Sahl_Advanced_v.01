import { useTranslation } from 'react-i18next';

import { Menu } from '../design-system';
import type { MenuItem } from '../design-system';
import { SUPPORTED_LANGUAGES, storeLanguage } from '../i18n';
import type { Language } from '../i18n';

const LABEL_KEY: Record<Language, string> = {
  ar: 'common:language.arabic',
  en: 'common:language.english',
};

export function LanguageMenu() {
  const { t, i18n } = useTranslation(['common']);

  const items: MenuItem[] = SUPPORTED_LANGUAGES.map((language) => ({
    id: language,
    label: t(LABEL_KEY[language]),
    selected: i18n.language === language,
    onSelect: () => {
      void i18n.changeLanguage(language);
      storeLanguage(language);
    },
  }));

  return <Menu label={t('common:language.change')} icon="globe" iconOnly onHeader items={items} />;
}
