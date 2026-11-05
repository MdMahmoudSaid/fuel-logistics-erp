// Report/statement dates are calendar dates: take the YYYY-MM-DD part of an
// ISO date or datetime as-is (no Date parsing, so no timezone drift) and
// print it JJ/MM/AAAA. Anything that is not an ISO date is returned as-is.
const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})(?:$|[T ])/

export function formatDateDMY(value: string): string {
  const match = ISO_DATE_RE.exec(value)
  return match ? `${match[3]}/${match[2]}/${match[1]}` : value
}

// Today's calendar date (YYYY-MM-DD) in the user's local time zone: the
// default for new-document date fields (toISOString would use UTC).
export function todayIso(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}
