// Blocks a non-digit character from ever appearing in a digits-only field
// (called on `beforeinput`). Pasted text is intentionally let through —
// the field's own `@input` handler strips non-digits from it — so pasting
// a formatted number like "12 34 56 78" still works.
export function blockNonDigitInput(event: Event): void {
  const inputEvent = event as InputEvent
  if (inputEvent.inputType === 'insertText' && inputEvent.data && /\D/.test(inputEvent.data)) {
    event.preventDefault()
  }
}
