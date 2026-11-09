// Prints a PDF without leaving the app (client request 2026-11-09): the app is
// installed as a PWA (desktop shortcut / phone), where a new browser tab breaks
// the "everything stays in the app" experience. The PDF is loaded into a hidden
// iframe and the print dialog is opened on it; the visible page is never
// replaced and no tab is opened.
//
// The servers send `Content-Security-Policy: default-src 'self' ...`; without a
// `frame-src ... blob:` entry the browser refuses the blob: iframe, `print()`
// throws a SecurityError and the button used to do nothing at all (found on
// AZUR and SAHEL 2026-11-09). When the frame is blocked we fall back to
// downloading the file, so a click always produces something.
const KEEP_ALIVE_MS = 60_000
const LOAD_TIMEOUT_MS = 15_000

function download(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

export function printPdfBlob(blob: Blob, filename = 'document.pdf'): Promise<void> {
  return new Promise((resolve) => {
    const url = window.URL.createObjectURL(blob)
    const frame = document.createElement('iframe')
    frame.setAttribute('aria-hidden', 'true')
    // 1px, not 0: some PDF viewers do not initialise in a zero-size frame.
    frame.style.cssText =
      'position:fixed;right:0;bottom:0;width:1px;height:1px;border:0;opacity:0;pointer-events:none;'

    let settled = false
    const cleanup = (delay: number) => {
      document.removeEventListener('securitypolicyviolation', onViolation)
      clearTimeout(timer)
      const remove = () => {
        frame.remove()
        window.URL.revokeObjectURL(url)
      }
      if (delay > 0) setTimeout(remove, delay)
      else remove()
    }
    const fallback = () => {
      if (settled) return
      settled = true
      cleanup(0)
      download(blob, filename)
      resolve()
    }
    function onViolation(event: SecurityPolicyViolationEvent) {
      if (
        event.violatedDirective.startsWith('frame-src') ||
        event.violatedDirective.startsWith('child-src')
      )
        fallback()
    }

    document.addEventListener('securitypolicyviolation', onViolation)
    const timer = setTimeout(fallback, LOAD_TIMEOUT_MS)
    frame.onload = () => {
      if (settled) return
      try {
        frame.contentWindow?.focus()
        frame.contentWindow?.print()
      } catch {
        fallback()
        return
      }
      settled = true
      resolve()
      // Keep the document alive while the print dialog is open.
      cleanup(KEEP_ALIVE_MS)
    }
    frame.src = url
    document.body.appendChild(frame)
  })
}
