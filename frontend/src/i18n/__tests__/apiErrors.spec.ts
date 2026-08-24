import { describe, it, expect } from 'vitest'
import { extractFieldErrors } from '../apiErrors'

describe('extractFieldErrors', () => {
  it('returns an empty object for undefined input', () => {
    expect(extractFieldErrors(undefined)).toEqual({})
  })

  it('maps each field to its first error message', () => {
    const result = extractFieldErrors({
      reference: ['Cette référence existe déjà.'],
      quantity: ['Doit être positif.'],
    })
    expect(result).toEqual({
      reference: 'Cette référence existe déjà.',
      quantity: 'Doit être positif.',
    })
  })

  it('ignores detail and non_field_errors keys', () => {
    const result = extractFieldErrors({
      detail: 'Erreur générique',
      non_field_errors: ['Erreur globale'],
      status: ['Valeur invalide.'],
    })
    expect(result).toEqual({ status: 'Valeur invalide.' })
  })

  it('accepts a plain string value for a field', () => {
    const result = extractFieldErrors({ notes: 'Trop long.' })
    expect(result).toEqual({ notes: 'Trop long.' })
  })
})
