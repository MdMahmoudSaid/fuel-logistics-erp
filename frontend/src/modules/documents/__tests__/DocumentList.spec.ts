import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import DocumentList from '../DocumentList.vue'

const push = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

const list = vi.fn()
const remove = vi.fn(async (_id: number) => undefined)
const downloadDocumentPdf = vi.fn(async () => undefined)
const printDocumentPdf = vi.fn(async () => undefined)
const post = vi.fn(async () => ({ data: { id: 99 } }))

vi.mock('../api', async (importOriginal) => ({
  listAll: (await importOriginal<typeof import('../api')>()).listAll,
  documentApi: () => ({ list: (p: unknown) => list(p), remove: (id: number) => remove(id) }),
  downloadDocumentPdf: (...a: unknown[]) => downloadDocumentPdf(...(a as [])),
  printDocumentPdf: (...a: unknown[]) => printDocumentPdf(...(a as [])),
}))
vi.mock('@/api/client', () => ({ apiClient: { post: (...a: unknown[]) => post(...(a as [])) } }))

// Row actions live in one "⋯" menu (teleported to <body>).
async function clickRowAction(
  wrapper: { find: (s: string) => { trigger: (e: string) => Promise<void> } },
  label: string,
) {
  document.body.querySelectorAll('[role=menu]').forEach((el) => el.remove())
  await wrapper.find('button[aria-label="Actions"]').trigger('click')
  const item = Array.from(document.body.querySelectorAll('[role=menuitem]')).find(
    (el) => el.textContent?.trim() === label,
  ) as HTMLElement
  item.click()
}

describe('DocumentList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    list.mockResolvedValue({
      results: [
        {
          id: 7,
          reference: 'BL-202610-0001',
          date: '2026-10-11',
          customer_detail: { name: 'Baba' },
          total_quantity: '90000.00',
        },
      ],
    })
  })

  it('lists delivery notes and downloads, prints and creates them', async () => {
    const wrapper = mount(DocumentList, { props: { kind: 'delivery' } })
    await flushPromises()
    expect(wrapper.text()).toContain('Bons de livraison')
    expect(wrapper.text()).toContain('BL-202610-0001')
    expect(wrapper.text()).toContain('Baba')
    expect(wrapper.find('[data-test="doc-status-filter"]').exists()).toBe(false)

    await clickRowAction(wrapper, 'PDF')
    expect(downloadDocumentPdf).toHaveBeenCalledWith(
      '/delivery-notes/',
      7,
      'bon-livraison-BL-202610-0001.pdf',
      'fr',
    )
    await clickRowAction(wrapper, 'Imprimer')
    expect(printDocumentPdf).toHaveBeenCalledWith('/delivery-notes/', 7, 'fr')
    await wrapper.find('[data-test="doc-new"]').trigger('click')
    expect(push).toHaveBeenCalledWith({ name: 'delivery-note-new' })
  })

  it('shows the status filter and duplicate action for proformas', async () => {
    list.mockResolvedValue({
      results: [
        {
          id: 3,
          reference: 'PF-202610-0001',
          issue_date: '2026-10-11',
          customer_name: 'SAHEL',
          total_amount: '387500000.00',
          status: 'DRAFT',
        },
      ],
    })
    const wrapper = mount(DocumentList, { props: { kind: 'proforma' } })
    await flushPromises()
    expect(wrapper.text()).toContain('Proformas')
    expect(wrapper.find('[data-test="doc-status-filter"]').exists()).toBe(true)
    await clickRowAction(wrapper, 'Dupliquer')
    await flushPromises()
    expect(post).toHaveBeenCalledWith('/quotations/3/duplicate/')
    expect(push).toHaveBeenCalledWith({ name: 'quotation-detail', params: { id: 99 } })
  })

  it('offers every row action in the single "⋯" menu, delete included', async () => {
    const wrapper = mount(DocumentList, { props: { kind: 'proforma' } })
    await flushPromises()
    document.body.querySelectorAll('[role=menu]').forEach((el) => el.remove())
    await wrapper.find('button[aria-label="Actions"]').trigger('click')
    const labels = Array.from(document.body.querySelectorAll('[role=menuitem]')).map((el) =>
      el.textContent?.trim(),
    )
    expect(labels).toEqual(['Dupliquer', 'PDF', 'Imprimer', 'Supprimer'])
    // No separate inline action buttons remain in the row.
    expect(wrapper.text()).not.toContain('Dupliquer')
  })

  it('loads every page, not only the first 25 documents', async () => {
    list
      .mockResolvedValueOnce({
        results: [{ id: 1, reference: 'BL-1', date: 'x', customer_detail: null }],
        next: 'p2',
      })
      .mockResolvedValueOnce({
        results: [{ id: 2, reference: 'BL-2', date: 'x', customer_detail: null }],
        next: null,
      })
    const wrapper = mount(DocumentList, { props: { kind: 'delivery' } })
    await flushPromises()
    expect(list).toHaveBeenCalledTimes(2)
    expect(list.mock.calls[1]![0]).toMatchObject({ page: 2 })
    expect(wrapper.text()).toContain('BL-2')
  })
})
