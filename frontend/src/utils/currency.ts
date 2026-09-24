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

function formatDecimal(value: number, decimals: number): string {
  return value
    .toLocaleString('fr-FR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    .replace(THOUSANDS_SEPARATOR_RE, ' ')
}

function isolateLtr(value: string): string {
  return `${LRI}${value}${PDI}`
}

/** `23 576 205 XOF` */
export function formatMoney(value: string | number): string {
  return isolateLtr(`${formatInteger(toNumber(value))} ${CURRENCY}`)
}

/** `0,6667 XOF/L` — 4 decimals (client request 2026-09-06: 2 decimals hid
 * enough precision that summing displayed per-litre prices back up (e.g.
 * every "Frais du trajet" line) visibly didn't reconstruct the real total -
 * a 30 000 XOF / 45 000 L fee showed as "0,67 XOF/L", and 0,67 x 45 000 =
 * 30 150, not 30 000. Matches the backend's own internal per-litre
 * precision (apps/trips/services.py `_UNIT = Decimal("0.0001")`), so this
 * is showing more of what was already computed, not inventing precision
 * that wasn't there. Per-litre costs are frequently sub-1-XOF, e.g. a
 * 10 000 XOF "par camion" fee on 45 000 L. */
export function formatUnitMoney(value: string | number): string {
  return isolateLtr(`${formatDecimal(toNumber(value), 4)} ${CURRENCY}/L`)
}

/** `12,50 %` — a share, never suffixed with the currency. */
export function formatPercent(value: string | number): string {
  return isolateLtr(`${formatDecimal(toNumber(value), 2)} %`)
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
