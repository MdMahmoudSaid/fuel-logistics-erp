// Official application currency is XOF (CFA). Never display a money amount
// without this suffix, and never use MRU - see docs/edit.md UI pass
// (2026-08-26).
const CURRENCY = 'XOF'
// Intl's fr-FR grouping uses no-break spaces (U+00A0 / U+202F); the app's
// amount format needs a plain, unambiguous space (23 576 205 XOF).
const THOUSANDS_SEPARATOR_RE = /[  ]/g
// The Arabic UI sets <html dir="rtl">. A grouped number like "23 576 205"
// has no strong-direction character, so the browser's bidi algorithm
// resolves its (neutral) space-separated groups against the RTL paragraph
// and reorders them (23 576 205 -> 205 576 23). Wrapping in an LTR isolate
// pins the whole formatted value as one LTR run wherever it's embedded
// (plain text, title attr, i18n interpolation).
const LRI = '⁦' // Left-to-Right Isolate
const PDI = '⁩' // Pop Directional Isolate

function toNumber(value: string | number): number {
  return typeof value === 'number' ? value : Number(value)
}

function formatInteger(value: number): string {
  return Math.round(value).toLocaleString('fr-FR').replace(THOUSANDS_SEPARATOR_RE, ' ')
}

function isolateLtr(value: string): string {
  return `${LRI}${value}${PDI}`
}

/** `23 576 205 XOF` */
export function formatMoney(value: string | number): string {
  return isolateLtr(`${formatInteger(toNumber(value))} ${CURRENCY}`)
}

/** `810 XOF/L` */
export function formatUnitMoney(value: string | number): string {
  return isolateLtr(`${formatInteger(toNumber(value))} ${CURRENCY}/L`)
}

/** `45 000 L` */
export function formatQuantity(value: string | number): string {
  return isolateLtr(`${formatInteger(toNumber(value))} L`)
}

/**
 * Same as formatMoney/formatQuantity but with the unit kept separate from
 * the digit group, so callers can style it distinctly (smaller, lighter,
 * non-mono) instead of gluing it onto the tabular digits - in IBM Plex Mono
 * Bold, a bare "XOF" reads as "X0F" (O and 0 render nearly identically at
 * that weight) when it's part of the same run as the amount.
 */
export function formatMoneyParts(value: string | number): { value: string; unit: string } {
  return { value: formatInteger(toNumber(value)), unit: CURRENCY }
}

export function formatQuantityParts(value: string | number): { value: string; unit: string } {
  return { value: formatInteger(toNumber(value)), unit: 'L' }
}
