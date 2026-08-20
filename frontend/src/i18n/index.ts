import { createI18n } from 'vue-i18n'
import fr from '@/locales/fr.json'
import en from '@/locales/en.json'

export const AVAILABLE_LOCALES = ['fr', 'en'] as const
export type AppLocale = (typeof AVAILABLE_LOCALES)[number]

const STORAGE_KEY = 'locale'
const DEFAULT_LOCALE: AppLocale = 'fr'

function isAppLocale(value: string | null): value is AppLocale {
  return !!value && (AVAILABLE_LOCALES as readonly string[]).includes(value)
}

function getStoredLocale(): AppLocale {
  const stored = localStorage.getItem(STORAGE_KEY)
  return isAppLocale(stored) ? stored : DEFAULT_LOCALE
}

export const i18n = createI18n({
  legacy: false,
  locale: getStoredLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages: { fr, en },
})

export function setLocale(locale: AppLocale) {
  i18n.global.locale.value = locale
  localStorage.setItem(STORAGE_KEY, locale)
  document.documentElement.lang = locale
}

document.documentElement.lang = i18n.global.locale.value
