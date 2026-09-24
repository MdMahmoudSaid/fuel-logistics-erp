// Print only one region of the page (docs/superpowers/specs/2026-09-23-
// rapports-document-comptable-design.md, section Print, D6). window.print()
// prints the whole document, and a CSS list of known shell elements (sidebar,
// topbar, ...) silently stops working the day the shell changes. Instead,
// right before printing, every sibling that is NOT on the path from the sheet
// up to <body> gets data-print-hidden, and the path itself data-print-chain
// (style.css resets its padding/overflow/height so the sheet can flow across
// pages). Everything is undone on afterprint, on unmount and if print()
// throws. Note: afterprint is the only cleanup signal that also works in
// browsers whose print() returns before the dialog closes.
import { getCurrentScope, onScopeDispose, type Ref } from 'vue'

const HIDDEN = 'data-print-hidden'
const CHAIN = 'data-print-chain'
const PAGE_STYLE_ID = 'report-page-size'

export type PrintOrientation = 'portrait' | 'landscape'

export function usePrintScope(
  sheet: Readonly<Ref<HTMLElement | null>>,
  orientation: Readonly<Ref<PrintOrientation>>,
): { print: () => void } {
  let undo: (() => void) | null = null

  function end() {
    undo?.()
    undo = null
  }

  function begin(root: HTMLElement) {
    end()
    const hidden: Element[] = []
    const chain: HTMLElement[] = []
    let node: HTMLElement | null = root
    while (node && node !== document.body) {
      chain.push(node)
      node.setAttribute(CHAIN, '')
      const parent: HTMLElement | null = node.parentElement
      for (const sibling of Array.from(parent?.children ?? [])) {
        if (sibling !== node) {
          sibling.setAttribute(HIDDEN, '')
          hidden.push(sibling)
        }
      }
      node = parent
    }

    const style = document.createElement('style')
    style.id = PAGE_STYLE_ID
    style.textContent = `@page { size: A4 ${orientation.value}; margin: 12mm; }`
    document.head.appendChild(style)

    const onAfterPrint = () => end()
    window.addEventListener('afterprint', onAfterPrint, { once: true })

    undo = () => {
      window.removeEventListener('afterprint', onAfterPrint)
      hidden.forEach((sibling) => sibling.removeAttribute(HIDDEN))
      chain.forEach((link) => link.removeAttribute(CHAIN))
      style.remove()
    }
  }

  function print() {
    const root = sheet.value
    if (!root) return
    begin(root)
    try {
      window.print()
    } catch (error) {
      end()
      throw error
    }
  }

  if (getCurrentScope()) onScopeDispose(end)

  return { print }
}
