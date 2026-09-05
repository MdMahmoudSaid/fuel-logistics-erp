import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import QuotationList from '../QuotationList.vue'
import type { Quotation } from '../types'

function makeQuotation(overrides: Partial<Quotation> = {}): Quotation {
  return {
    id: 7,
    reference: 'DEV-202609-0001',
    customer: 1,
    customer_detail: { id: 1, name: 'Client X', company_name: '' },
    customer_name: '',
    status: 'DRAFT',
    issue_date: '2026-09-05',
    validity_date: '2026-10-05',
    currency: 'XOF',
    total_amount: '700000.00',
    notes: '',
    lines: [],
    created_by: 1,
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

const list = vi.fn(async (params?: Record<string, unknown>) => {
  void params
  return paginated([makeQuotation()])
})
const duplicateQuotation = vi.fn(async (_id: number) => makeQuotation({ id: 100 }))
const exportQuotationPdf = vi.fn(async (_id: number, _reference: string, _lang: string) => undefined)

vi.mock('../api', () => ({
  quotationResource: { list: (params?: Record<string, unknown>) => list(params) },
  duplicateQuotation: (id: number) => duplicateQuotation(id),
  exportQuotationPdf: (id: number, reference: string, lang: string) =>
    exportQuotationPdf(id, reference, lang),
}))

function makeRouter() {
  const stub = { template: '<div />' }
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/quotations', name: 'quotations', component: QuotationList },
      { path: '/quotations/new', name: 'quotation-new', component: stub },
      { path: '/quotations/:id', name: 'quotation-detail', component: stub },
    ],
  })
}

describe('QuotationList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    list.mockResolvedValue(paginated([makeQuotation()]))
  })

  async function mountAt() {
    const router = makeRouter()
    router.push({ name: 'quotations' })
    await router.isReady()
    const wrapper = mount(QuotationList, { global: { plugins: [router] } })
    await flushPromises()
    return { wrapper, router }
  }

  it('lists quotations with reference, customer, total and status', async () => {
    const { wrapper } = await mountAt()

    expect(wrapper.text()).toContain('DEV-202609-0001')
    expect(wrapper.text()).toContain('Client X')
    expect(wrapper.text()).toContain('700 000')
    expect(wrapper.text()).toContain('Brouillon')
  })

  it('navigates to the detail page when a row is clicked', async () => {
    const { wrapper, router } = await mountAt()

    await wrapper.find('tbody tr').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('quotation-detail')
    expect(router.currentRoute.value.params.id).toBe('7')
  })

  it('filters by status', async () => {
    const { wrapper } = await mountAt()

    await wrapper.find('select').setValue('ACCEPTED')
    await flushPromises()

    expect(list).toHaveBeenLastCalledWith({ status: 'ACCEPTED' })
  })

  it('duplicates a quotation from the list and navigates to the copy', async () => {
    const { wrapper, router } = await mountAt()

    await wrapper.find('[data-test="quotation-duplicate"]').trigger('click')
    await flushPromises()

    expect(duplicateQuotation).toHaveBeenCalledWith(7)
    expect(router.currentRoute.value.params.id).toBe('100')
  })

  it('exports a quotation PDF from the list without navigating away', async () => {
    const { wrapper, router } = await mountAt()

    await wrapper.find('[data-test="quotation-pdf"]').trigger('click')
    await flushPromises()

    expect(exportQuotationPdf).toHaveBeenCalledWith(7, 'DEV-202609-0001', 'fr')
    expect(router.currentRoute.value.name).toBe('quotations')
  })
})
