import { afterEach, describe, expect, it, vi } from 'vitest'
import { printPdfBlob } from '../printPdf'

const pdf = () => new Blob(['%PDF'], { type: 'application/pdf' })

function stubUrl() {
  vi.stubGlobal('URL', { ...URL, createObjectURL: () => 'blob:x', revokeObjectURL: () => {} })
}

describe('printPdfBlob', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    vi.useRealTimers()
    document.querySelectorAll('iframe, a[download]').forEach((f) => f.remove())
  })

  it('prints through a hidden iframe and never opens a tab', async () => {
    const open = vi.spyOn(window, 'open')
    stubUrl()
    const done = printPdfBlob(pdf())
    const frame = document.querySelector('iframe') as HTMLIFrameElement
    expect(frame).not.toBeNull()
    const print = vi.fn()
    Object.defineProperty(frame, 'contentWindow', { value: { focus: vi.fn(), print } })
    frame.onload?.(new Event('load'))
    await done
    expect(print).toHaveBeenCalledOnce()
    expect(open).not.toHaveBeenCalled()
  })

  it('downloads the file instead when the browser blocks the frame (CSP)', async () => {
    stubUrl()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const done = printPdfBlob(pdf(), 'facture.pdf')
    const event = new Event('securitypolicyviolation') as Event & { violatedDirective: string }
    event.violatedDirective = 'frame-src'
    document.dispatchEvent(event)
    await done
    expect(click).toHaveBeenCalledOnce()
    expect(document.querySelector('iframe')).toBeNull()
  })

  it('downloads the file when print() throws a SecurityError', async () => {
    stubUrl()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const done = printPdfBlob(pdf())
    const frame = document.querySelector('iframe') as HTMLIFrameElement
    Object.defineProperty(frame, 'contentWindow', {
      get() {
        throw new DOMException('blocked', 'SecurityError')
      },
    })
    frame.onload?.(new Event('load'))
    await done
    expect(click).toHaveBeenCalledOnce()
  })
})
