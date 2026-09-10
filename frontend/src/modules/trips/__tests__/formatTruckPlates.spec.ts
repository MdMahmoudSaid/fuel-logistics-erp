import { describe, expect, it } from 'vitest'
import { formatTruckPlates } from '../formatTruckPlates'

describe('formatTruckPlates', () => {
  it('joins tractor and tanker registrations with a slash', () => {
    expect(
      formatTruckPlates({
        id: 1,
        internal_id: 'TRK-0001',
        tractor_registration: 'SN-1234-A',
        tanker_registration: 'SN-5678-B',
        capacity_litres: '45000',
        status: 'AVAILABLE',
      } as never),
    ).toBe('SN-1234-A / SN-5678-B')
  })

  it('falls back to an em dash when there is no truck', () => {
    expect(formatTruckPlates(null)).toBe('—')
    expect(formatTruckPlates(undefined)).toBe('—')
  })

  it('falls back to an em dash for a missing registration', () => {
    expect(
      formatTruckPlates({
        id: 1,
        internal_id: 'TRK-0001',
        tractor_registration: '',
        tanker_registration: 'SN-5678-B',
        capacity_litres: '45000',
        status: 'AVAILABLE',
      } as never),
    ).toBe('— / SN-5678-B')
  })
})
