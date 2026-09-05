import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import arCommon from './locales/ar/common.json';
import arDesignSystem from './locales/ar/designSystem.json';
import arHome from './locales/ar/home.json';
import arNavigation from './locales/ar/navigation.json';
import arStatus from './locales/ar/status.json';
import enCommon from './locales/en/common.json';
import enDesignSystem from './locales/en/designSystem.json';
import enHome from './locales/en/home.json';
import enNavigation from './locales/en/navigation.json';
import enStatus from './locales/en/status.json';

export const SUPPORTED_LANGUAGES = ['ar', 'en'] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

/** Arabic is the platform default on first visit. */
export const DEFAULT_LANGUAGE: Language = 'ar';

export const LANGUAGE_STORAGE_KEY = 'sahl.language';

export type Direction = 'rtl' | 'ltr';

export function directionOf(language: string): Direction {
  return language.startsWith('ar') ? 'rtl' : 'ltr';
}

function isSupported(value: string | null): value is Language {
  return value === 'ar' || value === 'en';
}

/**
 * Phase 1 keeps the preference in the browser. From Phase 2 it moves to the
 * user profile in the database; the reading side of the app does not change.
 */
export function readStoredLanguage(): Language | null {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return isSupported(stored) ? stored : null;
  } catch {
    return null;
  }
}

export function storeLanguage(language: Language): void {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // A browser that refuses storage must not break language switching.
  }
}

export const NAMESPACES = ['common', 'navigation', 'status', 'home', 'designSystem'] as const;

void i18n.use(initReactI18next).init({
  resources: {
    ar: {
      common: arCommon,
      navigation: arNavigation,
      status: arStatus,
      home: arHome,
      designSystem: arDesignSystem,
    },
    en: {
      common: enCommon,
      navigation: enNavigation,
      status: enStatus,
      home: enHome,
      designSystem: enDesignSystem,
    },
  },
  lng: readStoredLanguage() ?? DEFAULT_LANGUAGE,
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: SUPPORTED_LANGUAGES,
  defaultNS: 'common',
  ns: NAMESPACES,
  interpolation: { escapeValue: false },
});

export default i18n;
