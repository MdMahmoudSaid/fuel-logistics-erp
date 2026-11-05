import { describe, it, expect } from 'vitest'
import { formatDateDMY, todayIso } from '../date'

describe('formatDateDMY', () => {
  it('formats an ISO date as JJ/MM/AAAA', () => {
    expect(formatDateDMY('2026-09-02')).toBe('02/09/2026')
  })

  it('keeps the calendar date of an ISO datetime without timezone drift', () => {
    expect(formatDateDMY('2026-09-02T23:30:00+00:00')).toBe('02/09/2026')
    expect(formatDateDMY('2026-12-31T00:00:00Z')).toBe('31/12/2026')
  })

  it('returns anything that is not an ISO date unchanged', () => {
    expect(formatDateDMY('n/a')).toBe('n/a')
    expect(formatDateDMY('')).toBe('')
  })
})

describe('todayIso', () => {
  it('uses the local calendar date, padded', () => {
    expect(todayIso(new Date(2026, 10, 5, 23, 30))).toBe('2026-11-05')
    expect(todayIso(new Date(2026, 0, 9, 0, 5))).toBe('2026-01-09')
  })
})
