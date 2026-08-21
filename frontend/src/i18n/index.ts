import { createI18n } from 'vue-i18n'
import fr from '@/locales/fr.json'
import en from '@/locales/en.json'
import ar from '@/locales/ar.json'

export const AVAILABLE_LOCALES = ['fr', 'en', 'ar'] as const
export type AppLocale = (typeof AVAILABLE_LOCALES)[number]

export const RTL_LOCALES = new Set<AppLocale>(['ar'])

const STORAGE_KEY = 'locale'
const DEFAULT_LOCALE: AppLocale = 'fr'

function isAppLocale(value: string | null): value is AppLocale {
  return !!value && (AVAILABLE_LOCALES as readonly string[]).includes(value)
}

function getStoredLocale(): AppLocale {
  const stored = localStorage.getItem(STORAGE_KEY)
  return isAppLocale(stored) ? stored : DEFAULT_LOCALE
}

function applyDocumentDirection(locale: AppLocale) {
  document.documentElement.dir = RTL_LOCALES.has(locale) ? 'rtl' : 'ltr'
  document.documentElement.lang = locale
}

export const i18n = createI18n({
  legacy: false,
  locale: getStoredLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages: { fr, en, ar },
})

export function setLocale(locale: AppLocale) {
  i18n.global.locale.value = locale
  localStorage.setItem(STORAGE_KEY, locale)
  applyDocumentDirection(locale)
}

applyDocumentDirection(i18n.global.locale.value as AppLocale)
