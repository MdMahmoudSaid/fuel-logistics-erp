import { describe, it, expect } from 'vitest'
import {
  COUNTRIES,
  PRIORITY_ISO2,
  PHONE_DIGIT_RULES,
  DEFAULT_DIGIT_RULE,
  DEFAULT_ISO2,
  formatPhoneDisplay,
} from '@/data/countries'

describe('countries data', () => {
  it('includes the four priority Sahel countries with exact digit rules', () => {
    expect(PRIORITY_ISO2).toEqual(['MR', 'ML', 'SN', 'NE'])
    expect(PHONE_DIGIT_RULES.MR).toEqual({ min: 8, max: 8 })
    expect(PHONE_DIGIT_RULES.ML).toEqual({ min: 8, max: 8 })
    expect(PHONE_DIGIT_RULES.SN).toEqual({ min: 9, max: 9 })
    expect(PHONE_DIGIT_RULES.NE).toEqual({ min: 8, max: 8 })
  })

  it('has a unique entry per ISO2 code and covers every priority country', () => {
    const codes = COUNTRIES.map((c) => c.iso2)
    expect(new Set(codes).size).toBe(codes.length)
    for (const iso2 of PRIORITY_ISO2) {
      expect(codes).toContain(iso2)
    }
  })

  it('falls back to the default digit rule and default country for unlisted codes', () => {
    expect(PHONE_DIGIT_RULES.XX).toBeUndefined()
    expect(DEFAULT_DIGIT_RULE).toEqual({ min: 6, max: 14 })
    expect(COUNTRIES.some((c) => c.iso2 === DEFAULT_ISO2)).toBe(true)
  })

  it('formats a normalized phone value with a space between the dial code and the number', () => {
    expect(formatPhoneDisplay('+22212340000')).toBe('+222 12340000')
    expect(formatPhoneDisplay('+22112345678')).toBe('+221 12345678')
  })

  it('returns the raw value unchanged when it has no matching dial code or is empty', () => {
    expect(formatPhoneDisplay('')).toBe('')
    expect(formatPhoneDisplay('not-a-phone')).toBe('not-a-phone')
  })
})
