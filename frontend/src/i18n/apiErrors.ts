// The backend is French-first (Django LANGUAGE_CODE=fr-fr, see
// backend/config/settings/base.py) and its own `detail=`/ValidationError
// messages are already written in French — so a `detail` string from the
// API can normally be shown to the user as-is. This only exists as a
// defense-in-depth net for the handful of messages that were still
// hard-coded in English before the backend i18n fix (or might regress).
const KNOWN_ENGLISH_PATTERNS: [RegExp, (match: RegExpMatchArray) => string][] = [
  [/^Unknown module: (.+)$/, (m) => `Module inconnu : ${m[1]}`],
  [/^Unknown actions: (.+)$/, (m) => `Actions inconnues : ${m[1]}`],
]

export function translateApiError(detail: string | undefined | null): string | undefined {
  if (!detail) return undefined
  for (const [pattern, translate] of KNOWN_ENGLISH_PATTERNS) {
    const match = detail.match(pattern)
    if (match) return translate(match)
  }
  return detail
}

export function extractFieldErrors(
  data: Record<string, unknown> | undefined | null,
): Record<string, string> {
  const fieldErrors: Record<string, string> = {}
  if (!data) return fieldErrors
  for (const [field, value] of Object.entries(data)) {
    if (field === 'detail' || field === 'non_field_errors') continue
    const message = Array.isArray(value) ? value[0] : value
    if (typeof message === 'string') fieldErrors[field] = message
  }
  return fieldErrors
}
