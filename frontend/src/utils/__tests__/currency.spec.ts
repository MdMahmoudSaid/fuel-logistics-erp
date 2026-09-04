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
  it('renders 2 decimals with a comma separator, not rounded to 0', () => {
    // 10 000 XOF / 45 000 L = 0.2222... XOF/L
    expect(stripBidiIsolate(formatUnitMoney(10000 / 45000))).toBe('0,22 XOF/L')
  })

  it('still renders whole values with 2 decimals', () => {
    expect(stripBidiIsolate(formatUnitMoney(810))).toBe('810,00 XOF/L')
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
    expect(formatUnitMoney(810)).toBe(`${LRI}810,00 XOF/L${PDI}`)
    expect(formatQuantity(45000)).toBe(`${LRI}45 000 L${PDI}`)
  })
})
