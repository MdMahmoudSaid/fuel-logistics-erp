import { describe, it, expect } from 'vitest'
import {
  sumField,
  averageLossPercent,
  unjustifiedLosses,
  lastNDays,
  groupVolumeByDay,
  type LossReportRow,
} from '../aggregate'

function row(overrides: Partial<LossReportRow>): LossReportRow {
  return {
    trip_reference: 'TRIP-000001',
    control_date: '2026-08-20',
    loaded_quantity: '10000.00',
    received_quantity: '9950.00',
    loss_quantity: '50.00',
    tolerance_quantity: '100.00',
    chargeable_loss_quantity: '0.00',
    ...overrides,
  }
}

describe('sumField', () => {
  it('sums the requested field across rows', () => {
    const rows = [row({ received_quantity: '100' }), row({ received_quantity: '250' })]
    expect(sumField(rows, 'received_quantity')).toBe(350)
  })

  it('returns 0 for an empty list', () => {
    expect(sumField([], 'loaded_quantity')).toBe(0)
  })
})

describe('averageLossPercent', () => {
  it('averages loss/loaded per row, not volume-weighted', () => {
    const rows = [
      row({ loaded_quantity: '10000', loss_quantity: '100' }), // 1%
      row({ loaded_quantity: '1000', loss_quantity: '100' }), // 10%
    ]
    expect(averageLossPercent(rows)).toBeCloseTo(5.5, 5)
  })

  it('returns 0 when there are no rows with a positive loaded quantity', () => {
    expect(averageLossPercent([])).toBe(0)
    expect(averageLossPercent([row({ loaded_quantity: '0' })])).toBe(0)
  })
})

describe('unjustifiedLosses', () => {
  it('keeps only rows with a chargeable loss, sorted descending', () => {
    const rows = [
      row({ trip_reference: 'TRIP-A', chargeable_loss_quantity: '0' }),
      row({ trip_reference: 'TRIP-B', chargeable_loss_quantity: '40' }),
      row({ trip_reference: 'TRIP-C', chargeable_loss_quantity: '120' }),
    ]
    expect(unjustifiedLosses(rows).map((r) => r.trip_reference)).toEqual(['TRIP-C', 'TRIP-B'])
  })
})

describe('lastNDays / groupVolumeByDay', () => {
  it('builds n consecutive days ending today, and flags today', () => {
    const today = new Date('2026-08-20T12:00:00Z')
    const days = lastNDays(14, today)
    expect(days).toHaveLength(14)
    expect(days[13]!.date).toBe('2026-08-20')
    expect(days[13]!.isToday).toBe(true)
    expect(days[0]!.isToday).toBe(false)
  })

  it('groups received quantity by control_date onto the day skeleton', () => {
    const days = lastNDays(3, new Date('2026-08-20T12:00:00Z'))
    const rows = [
      row({ control_date: '2026-08-20', received_quantity: '1000' }),
      row({ control_date: '2026-08-20', received_quantity: '500' }),
      row({ control_date: '2026-08-19', received_quantity: '750' }),
    ]
    const grouped = groupVolumeByDay(rows, days)
    expect(grouped.find((d) => d.date === '2026-08-20')?.value).toBe(1500)
    expect(grouped.find((d) => d.date === '2026-08-19')?.value).toBe(750)
    expect(grouped.find((d) => d.date === '2026-08-18')?.value).toBe(0)
  })
})
