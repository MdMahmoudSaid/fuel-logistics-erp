import { describe, it, expect } from 'vitest'
import { blockNonDigitInput } from '@/utils/numeric-input'

function beforeInputEvent(inputType: string, data: string | null) {
  return new InputEvent('beforeinput', { inputType, data, cancelable: true })
}

describe('blockNonDigitInput', () => {
  it('prevents a typed letter from being inserted', () => {
    const event = beforeInputEvent('insertText', 'a')
    blockNonDigitInput(event)
    expect(event.defaultPrevented).toBe(true)
  })

  it('allows a typed digit', () => {
    const event = beforeInputEvent('insertText', '5')
    blockNonDigitInput(event)
    expect(event.defaultPrevented).toBe(false)
  })

  it('allows pasted text through so it can be digit-stripped on input instead', () => {
    const event = beforeInputEvent('insertFromPaste', '12a34')
    blockNonDigitInput(event)
    expect(event.defaultPrevented).toBe(false)
  })

  it('allows deletion (no inserted data)', () => {
    const event = beforeInputEvent('deleteContentBackward', null)
    blockNonDigitInput(event)
    expect(event.defaultPrevented).toBe(false)
  })
})
