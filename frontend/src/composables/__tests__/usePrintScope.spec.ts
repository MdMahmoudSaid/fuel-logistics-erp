import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { usePrintScope } from '../usePrintScope'

// docs/superpowers/specs/2026-09-23-rapports-document-comptable-design.md,
// section Print (D6): everything outside the report sheet is hidden
// explicitly - every sibling not on the sheet's ancestor chain, whatever the
// app shell looks like - and cleaned up afterwards.

function el(tag: string, attrs: Record<string, string> = {}, children: HTMLElement[] = []) {
  const node = document.createElement(tag)
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value)
  children.forEach((child) => node.appendChild(child))
  return node
}

// body > #app > [aside, .layout > [header, main > [h1, .toolbar, .sheet-wrap > .sheet, .footnote], .drawer], .toast (teleported)]
function buildShell() {
  const sheet = el('div', { class: 'sheet' })
  const sheetWrap = el('div', { class: 'sheet-wrap' }, [sheet])
  const main = el('main', {}, [
    el('h1'),
    el('div', { class: 'toolbar' }),
    sheetWrap,
    el('p', { class: 'footnote' }),
  ])
  const layout = el('div', { class: 'layout' }, [
    el('header'),
    main,
    el('div', { class: 'drawer' }),
  ])
  const app = el('div', { id: 'app' }, [el('aside'), layout])
  const toast = el('div', { class: 'toast' })
  document.body.append(app, toast)
  return { sheet, sheetWrap, main, layout, app, toast }
}

const pageStyle = () => document.getElementById('report-page-size')
const hidden = () => Array.from(document.querySelectorAll('[data-print-hidden]'))
const chain = () => Array.from(document.querySelectorAll('[data-print-chain]'))

describe('usePrintScope', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })
  afterEach(() => {
    vi.restoreAllMocks()
    window.dispatchEvent(new Event('afterprint'))
    document.body.innerHTML = ''
  })

  it('hides every off-chain sibling at every depth and keeps the sheet and its ancestors', () => {
    const { sheet, sheetWrap, main, layout, app, toast } = buildShell()
    const printed = vi.fn(() => {
      const hiddenClasses = hidden().map((node) => node.className || node.tagName.toLowerCase())
      expect(hiddenClasses.sort()).toEqual(
        ['aside', 'drawer', 'footnote', 'h1', 'header', 'toast', 'toolbar'].sort(),
      )
      for (const node of [sheet, sheetWrap, main, layout, app, document.body]) {
        expect(node.hasAttribute('data-print-hidden')).toBe(false)
      }
      expect(toast.hasAttribute('data-print-hidden')).toBe(true)
      expect(chain()).toEqual(expect.arrayContaining([sheetWrap, main, layout, app]))
    })
    vi.spyOn(window, 'print').mockImplementation(printed)

    usePrintScope(ref(sheet), ref('portrait')).print()

    expect(printed).toHaveBeenCalledTimes(1)
  })

  it('sets the @page size from the orientation for the duration of the print', () => {
    const { sheet } = buildShell()
    const sizes: string[] = []
    vi.spyOn(window, 'print').mockImplementation(() => {
      sizes.push(pageStyle()?.textContent ?? '')
    })

    usePrintScope(ref(sheet), ref('landscape')).print()
    window.dispatchEvent(new Event('afterprint'))
    usePrintScope(ref(sheet), ref('portrait')).print()

    expect(sizes[0]).toContain('size: A4 landscape')
    expect(sizes[1]).toContain('size: A4 portrait')
    expect(sizes[1]).not.toContain('landscape')
  })

  it('removes every marker and the page-size style after afterprint', () => {
    const { sheet } = buildShell()
    vi.spyOn(window, 'print').mockImplementation(() => {})

    usePrintScope(ref(sheet), ref('portrait')).print()
    expect(hidden().length).toBeGreaterThan(0)
    expect(pageStyle()).not.toBeNull()

    window.dispatchEvent(new Event('afterprint'))

    expect(hidden()).toHaveLength(0)
    expect(chain()).toHaveLength(0)
    expect(pageStyle()).toBeNull()
  })

  it('cleans up and rethrows when print() throws', () => {
    const { sheet } = buildShell()
    vi.spyOn(window, 'print').mockImplementation(() => {
      throw new Error('print blocked')
    })

    expect(() => usePrintScope(ref(sheet), ref('portrait')).print()).toThrow('print blocked')

    expect(hidden()).toHaveLength(0)
    expect(chain()).toHaveLength(0)
    expect(pageStyle()).toBeNull()
  })

  it('cleans up when the component using it unmounts mid-print', async () => {
    const { sheet } = buildShell()
    vi.spyOn(window, 'print').mockImplementation(() => {})
    const Host = defineComponent({
      setup() {
        const { print } = usePrintScope(ref(sheet), ref('portrait'))
        return () => h('button', { onClick: print }, 'print')
      },
    })
    const wrapper = mount(Host)

    await wrapper.find('button').trigger('click')
    await nextTick()
    expect(hidden().length).toBeGreaterThan(0)

    wrapper.unmount()

    expect(hidden()).toHaveLength(0)
    expect(pageStyle()).toBeNull()
  })

  it('does nothing when there is no sheet, and printing twice never stacks markers or styles', () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    usePrintScope(ref(null), ref('portrait')).print()
    expect(printSpy).not.toHaveBeenCalled()

    const { sheet } = buildShell()
    const scope = usePrintScope(ref(sheet), ref('portrait'))
    scope.print()
    scope.print()

    expect(document.querySelectorAll('#report-page-size')).toHaveLength(1)
    window.dispatchEvent(new Event('afterprint'))
    expect(hidden()).toHaveLength(0)
  })
})
