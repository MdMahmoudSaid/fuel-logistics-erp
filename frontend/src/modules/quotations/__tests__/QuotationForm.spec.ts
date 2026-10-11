import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import QuotationForm from '../QuotationForm.vue'
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
    notes: 'Conditions',
    payment_terms: '',
    show_bank_accounts: true,
    lines: [
      {
        id: 1,
        product: 1,
        product_detail: { id: 1, name: 'Gasoil', code: 'gasoil' },
        description: '',
        quantity: '1000.00',
        unit: 'L',
        unit_price: '650.0000',
        line_total: '650000.00',
      },
      {
        id: 2,
        product: null,
        product_detail: null,
        description: 'Frais de livraison',
        quantity: '1.00',
        unit: 'forfait',
        unit_price: '50000.0000',
        line_total: '50000.00',
      },
    ],
    created_by: 1,
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

const customerList = vi.fn(async () => paginated([{ id: 1, name: 'Client X', company_name: '' }]))
const productList = vi.fn(async () => paginated([{ id: 1, name: 'Gasoil', code: 'gasoil' }]))

vi.mock('@/api/resource', () => ({
  createResourceApi: (path: string) => {
    if (path === '/customers/') return { list: customerList }
    if (path === '/products/') return { list: productList }
    throw new Error(`unexpected resource path in test: ${path}`)
  },
}))

let quotationToReturn: Quotation
const createQuotation = vi.fn(async (payload: Record<string, unknown>) => ({
  id: 99,
  ...payload,
}))
const updateQuotation = vi.fn(async (_id: number, payload: Record<string, unknown>) => ({
  ...quotationToReturn,
  ...payload,
}))
const duplicateQuotation = vi.fn(async (_id: number) => ({ ...quotationToReturn, id: 100 }))
const exportQuotationPdf = vi.fn(
  async (_id: number, _reference: string, _lang: string) => undefined,
)

vi.mock('../api', () => ({
  quotationResource: {
    get: (_id: number) => Promise.resolve(quotationToReturn),
    create: (payload: Record<string, unknown>) => createQuotation(payload),
    update: (id: number, payload: Record<string, unknown>) => updateQuotation(id, payload),
  },
  duplicateQuotation: (id: number) => duplicateQuotation(id),
  exportQuotationPdf: (id: number, reference: string, lang: string) =>
    exportQuotationPdf(id, reference, lang),
}))

function makeRouter() {
  const stub = { template: '<div />' }
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/quotations', name: 'quotations', component: stub },
      { path: '/quotations/new', name: 'quotation-new', component: QuotationForm },
      { path: '/quotations/:id', name: 'quotation-detail', component: QuotationForm },
    ],
  })
}

describe('QuotationForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    customerList.mockResolvedValue(paginated([{ id: 1, name: 'Client X', company_name: '' }]))
    productList.mockResolvedValue(paginated([{ id: 1, name: 'Gasoil', code: 'gasoil' }]))
  })

  it('creates a quotation with multiple lines and posts the computed payload', async () => {
    const router = makeRouter()
    router.push({ name: 'quotation-new' })
    await router.isReady()
    const wrapper = mount(QuotationForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#customer_name').setValue('Prospect ABC')
    const lineRows = wrapper.findAll('[data-test="quotation-line"]')
    await lineRows[0]!.find('input[type="number"][step="0.01"]').setValue('1000')
    await lineRows[0]!.find('input[type="number"][step="0.0001"]').setValue('650')
    await wrapper.find('#payment_terms').setValue('Avance de 30% obligatoire')
    await wrapper.find('#show_bank_accounts').setValue(false)

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(createQuotation).toHaveBeenCalledWith(
      expect.objectContaining({
        customer_name: 'Prospect ABC',
        payment_terms: 'Avance de 30% obligatoire',
        show_bank_accounts: false,
        lines: [expect.objectContaining({ quantity: '1000', unit_price: '650' })],
      }),
    )
  })

  it('shows the live computed total as lines are filled in', async () => {
    const router = makeRouter()
    router.push({ name: 'quotation-new' })
    await router.isReady()
    const wrapper = mount(QuotationForm, { global: { plugins: [router] } })
    await flushPromises()

    const lineRow = wrapper.find('[data-test="quotation-line"]')
    await lineRow.find('input[type="number"][step="0.01"]').setValue('10')
    await lineRow.find('input[type="number"][step="0.0001"]').setValue('1000')

    expect(wrapper.text().replace(/[⁦⁩]/g, '')).toContain('10 000 XOF')
  })

  it('adds and removes line rows, always keeping at least one', async () => {
    const router = makeRouter()
    router.push({ name: 'quotation-new' })
    await router.isReady()
    const wrapper = mount(QuotationForm, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.findAll('[data-test="quotation-line"]')).toHaveLength(1)

    const addButton = wrapper.findAll('button').find((b) => b.text() === '+ Ajouter une ligne')
    await addButton!.trigger('click')
    expect(wrapper.findAll('[data-test="quotation-line"]')).toHaveLength(2)

    const removeButtons = wrapper.findAll('[data-test="quotation-line-remove"]')
    await removeButtons[0]!.trigger('click')
    expect(wrapper.findAll('[data-test="quotation-line"]')).toHaveLength(1)

    // The last remaining line can't be removed (disabled).
    const lastRemoveButton = wrapper.find('[data-test="quotation-line-remove"]')
    expect((lastRemoveButton.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('loads an existing quotation and pre-fills the form, including both lines', async () => {
    quotationToReturn = makeQuotation()
    const router = makeRouter()
    router.push({ name: 'quotation-detail', params: { id: '7' } })
    await router.isReady()
    const wrapper = mount(QuotationForm, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.findAll('[data-test="quotation-line"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('DEV-202609-0001')
  })

  it('duplicates an existing quotation and navigates to the copy', async () => {
    quotationToReturn = makeQuotation()
    const router = makeRouter()
    router.push({ name: 'quotation-detail', params: { id: '7' } })
    await router.isReady()
    const wrapper = mount(QuotationForm, { global: { plugins: [router] } })
    await flushPromises()

    const duplicateButton = wrapper.findAll('button').find((b) => b.text() === 'Dupliquer')
    await duplicateButton!.trigger('click')
    await flushPromises()

    expect(duplicateQuotation).toHaveBeenCalledWith(7)
    expect(router.currentRoute.value.params.id).toBe('100')
  })

  it('exports the quotation PDF with the current locale', async () => {
    quotationToReturn = makeQuotation()
    const router = makeRouter()
    router.push({ name: 'quotation-detail', params: { id: '7' } })
    await router.isReady()
    const wrapper = mount(QuotationForm, { global: { plugins: [router] } })
    await flushPromises()

    const exportButton = wrapper.findAll('button').find((b) => b.text() === 'Exporter PDF')
    await exportButton!.trigger('click')
    await flushPromises()

    expect(exportQuotationPdf).toHaveBeenCalledWith(7, 'DEV-202609-0001', 'fr')
  })
})
