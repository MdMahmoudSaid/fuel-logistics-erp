import { afterEach, describe, expect, it, vi } from 'vitest'
import { printPdfBlob } from '../printPdf'

describe('printPdfBlob', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.querySelectorAll('iframe').forEach((f) => f.remove())
  })

  it('prints through a hidden iframe and never opens a tab', async () => {
    const open = vi.spyOn(window, 'open')
    vi.stubGlobal('URL', { ...URL, createObjectURL: () => 'blob:x', revokeObjectURL: () => {} })
    const done = printPdfBlob(new Blob(['%PDF'], { type: 'application/pdf' }))
    const frame = document.querySelector('iframe') as HTMLIFrameElement
    expect(frame).not.toBeNull()
    const print = vi.fn()
    Object.defineProperty(frame, 'contentWindow', { value: { focus: vi.fn(), print } })
    frame.onload?.(new Event('load'))
    await done
    expect(print).toHaveBeenCalledOnce()
    expect(open).not.toHaveBeenCalled()
  })
})
