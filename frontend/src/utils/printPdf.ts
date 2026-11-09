// Prints a PDF without leaving the app (client request 2026-11-09): the app is
// installed as a PWA (desktop shortcut / phone), where a new browser tab breaks
// the "everything stays in the app" experience. The PDF is loaded into a hidden
// iframe and the print dialog is opened on it; the visible page is never
// replaced and no tab is opened.
const KEEP_ALIVE_MS = 60_000

export function printPdfBlob(blob: Blob): Promise<void> {
  return new Promise((resolve) => {
    const url = window.URL.createObjectURL(blob)
    const frame = document.createElement('iframe')
    frame.setAttribute('aria-hidden', 'true')
    frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;'
    frame.onload = () => {
      try {
        frame.contentWindow?.focus()
        frame.contentWindow?.print()
      } finally {
        resolve()
        // Keep the document alive while the print dialog is open.
        setTimeout(() => {
          frame.remove()
          window.URL.revokeObjectURL(url)
        }, KEEP_ALIVE_MS)
      }
    }
    frame.src = url
    document.body.appendChild(frame)
  })
}
