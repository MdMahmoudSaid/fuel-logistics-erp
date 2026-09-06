import { describe, it, expect } from 'vitest'
import { formatMoney, formatUnitMoney, formatQuantity } from '@/utils/currency'

// Every formatter wraps its output in LRI/PDI (bidi isolate) marks so the
// value can't be reordered when embedded in an RTL (Arabic) page - see
// currency.ts. Strip them here so these tests assert visible content only.
const LRI = '⁦'
const PDI = '⁩'
function stripBidiIsolate(value: string): string {
  expect(value.startsWith(LRI)).toBe(true)
  expect(value.endsWith(PDI)).toBe(true)
  return value.slice(LRI.length, -PDI.length)
}

describe('formatMoney', () => {
  it('groups thousands with a narrow space and appends XOF', () => {
    expect(stripBidiIsolate(formatMoney(23576205))).toBe('23 576 205 XOF')
  })

  it('accepts a string amount', () => {
    expect(stripBidiIsolate(formatMoney('900000.00'))).toBe('900 000 XOF')
  })

  it('rounds to the nearest integer', () => {
    expect(stripBidiIsolate(formatMoney(1234.6))).toBe('1 235 XOF')
  })
})

describe('formatUnitMoney', () => {
  // Client request (2026-09-06): 2 decimals hid enough precision that
  // summing displayed per-litre prices back up visibly didn't reconstruct
  // the real total (a 30 000 XOF / 45 000 L fee showed as "0,67 XOF/L",
  // and 0,67 x 45 000 = 30 150, not 30 000) - 4 decimals matches the
  // backend's own internal per-litre precision (_UNIT = Decimal("0.0001")).
  it('renders 4 decimals with a comma separator, not rounded to 0', () => {
    // 10 000 XOF / 45 000 L = 0.2222222... XOF/L
    expect(stripBidiIsolate(formatUnitMoney(10000 / 45000))).toBe('0,2222 XOF/L')
  })

  it('rounds up correctly, not truncating (30 000 / 45 000 = 0.66666... -> 0,6667, not 0,6666)', () => {
    expect(stripBidiIsolate(formatUnitMoney(30000 / 45000))).toBe('0,6667 XOF/L')
  })

  it('still renders whole values with 4 decimals', () => {
    expect(stripBidiIsolate(formatUnitMoney(810))).toBe('810,0000 XOF/L')
  })
})

describe('formatQuantity', () => {
  it('appends L', () => {
    expect(stripBidiIsolate(formatQuantity(45000))).toBe('45 000 L')
  })
})

describe('formatMoney / formatQuantity (unchanged, still integer-rounded)', () => {
  it('formatMoney stays rounded to 0 decimals', () => {
    expect(stripBidiIsolate(formatMoney(23576205.6))).not.toContain(',')
  })
  it('formatQuantity stays rounded to 0 decimals', () => {
    expect(stripBidiIsolate(formatQuantity(45000.4))).not.toContain(',')
  })
})

describe('bidi isolation', () => {
  it('wraps formatted values in LRI/PDI so RTL contexts cannot reorder them', () => {
    expect(formatMoney(23576205)).toBe(`${LRI}23 576 205 XOF${PDI}`)
    expect(formatUnitMoney(810)).toBe(`${LRI}810,0000 XOF/L${PDI}`)
    expect(formatQuantity(45000)).toBe(`${LRI}45 000 L${PDI}`)
  })
})
