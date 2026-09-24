// Report/statement dates are calendar dates: take the YYYY-MM-DD part of an
// ISO date or datetime as-is (no Date parsing, so no timezone drift) and
// print it JJ/MM/AAAA. Anything that is not an ISO date is returned as-is.
const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})(?:$|[T ])/

export function formatDateDMY(value: string): string {
  const match = ISO_DATE_RE.exec(value)
  return match ? `${match[3]}/${match[2]}/${match[1]}` : value
}
