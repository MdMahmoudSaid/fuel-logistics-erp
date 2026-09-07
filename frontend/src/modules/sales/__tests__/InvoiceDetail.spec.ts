import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import InvoiceDetail from '../InvoiceDetail.vue'
import { useAuthStore } from '@/stores/auth'
import type { Invoice } from '../types'

function makeInvoice(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: 3,
    invoice_number: 'INV-TRIP-001',
    sale: 5,
    sale_detail: {
      id: 5,
      trip: 9,
      trip_reference: 'TRIP-001',
      customer: 1,
      customer_detail: { id: 1, name: 'Client X', company_name: '' },
      product: 1,
      product_detail: { id: 1, name: 'Gasoil', code: 'gasoil' },
      delivered_quantity: '44850.00',
      quantity_loaded: '45000.00',
      unit_selling_price: '650.0000',
      currency: 'XOF',
      subtotal: '29152500.00',
      created_at: '',
      updated_at: '',
    },
    status: 'DRAFT',
    total_amount: '29152500.00',
    paid_amount: '0.00',
    outstanding_amount: '29152500.00',
    issued_date: '2026-08-18',
    corrections: [],
    payments: [],
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

let invoiceToReturn: Invoice
const updateInvoice = vi.fn(async (_id: number, payload: Record<string, unknown>) => ({
  ...invoiceToReturn,
  ...payload,
}))
const validateInvoice = vi.fn(async (id: number) => {
  void id
  return { ...invoiceToReturn, status: 'VALIDATED' } as Invoice
})
const correctInvoice = vi.fn(
  async (_id: number, field: string, newValue: string, reason: string) =>
    ({
      ...invoiceToReturn,
      total_amount: '29377500.00',
      corrections: [
        {
          id: 1,
          field_name: field,
          previous_value: '650.0000',
          new_value: newValue,
          corrected_by: 1,
          corrected_by_detail: null,
          corrected_at: '2026-08-18T10:00:00Z',
          reason,
        },
      ],
    }) as Invoice,
)

vi.mock('../api', () => ({
  invoiceResource: {
    get: vi.fn(async () => invoiceToReturn),
    update: (id: number, payload: Record<string, unknown>) => updateInvoice(id, payload),
  },
  validateInvoice: (id: number) => validateInvoice(id),
  correctInvoice: (id: number, field: string, newValue: string, reason: string) =>
    correctInvoice(id, field, newValue, reason),
}))

function setAdminUser() {
  const auth = useAuthStore()
  auth.user = {
    id: 1,
    phone: '+22212345678',
    email: 'admin@example.com',
    full_name: 'Admin',
    role: 1,
    role_detail: { id: 1, name: 'Admin', permissions: { sales: ['view', 'edit', 'validate'] } },
  }
}

function makeRouter() {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/invoices', name: 'invoices', component: stub },
      { path: '/invoices/:id', name: 'invoice-detail', component: InvoiceDetail },
      { path: '/trips/:id', name: 'trip-detail', component: stub },
      { path: '/customers/:id/ledger', name: 'customer-ledger', component: stub },
    ],
  })
  return router
}

describe('InvoiceDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('shows the sale-derived quantity and total for a DRAFT invoice, editable fields, and a validate button', async () => {
    setAdminUser()
    invoiceToReturn = makeInvoice()
    const router = makeRouter()
    router.push({ name: 'invoice-detail', params: { id: '3' } })
    await router.isReady()
    const wrapper = mount(InvoiceDetail, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('44 850 L')
    expect(wrapper.find('#total_amount').exists()).toBe(true)
    expect((wrapper.find('#total_amount').element as HTMLInputElement).value).toBe('29152500.00')
    expect(wrapper.find('button#validate-invoice').exists()).toBe(true)
    expect(wrapper.find('button#correct-invoice').exists()).toBe(false)
  })

  it('shows the loaded quantity next to the received quantity', async () => {
    setAdminUser()
    invoiceToReturn = makeInvoice()
    const router = makeRouter()
    router.push({ name: 'invoice-detail', params: { id: '3' } })
    await router.isReady()
    const wrapper = mount(InvoiceDetail, { global: { plugins: [router] } })
    await flushPromises()

    const text = wrapper.text().replace(/[⁦⁩]/g, '')
    expect(text).toContain('Quantité chargée')
    expect(text).toContain('45 000 L')
  })

  it('offers delivered_quantity as a correctable field', async () => {
    setAdminUser()
    invoiceToReturn = makeInvoice({ status: 'VALIDATED' })
    const router = makeRouter()
    router.push({ name: 'invoice-detail', params: { id: '3' } })
    await router.isReady()
    const wrapper = mount(InvoiceDetail, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('button#correct-invoice').trigger('click')
    await flushPromises()

    const options = wrapper
      .find('#correction_field')
      .findAll('option')
      .map((o) => o.text())
    expect(options).toContain('Quantité livrée')
  })

  it('validates the invoice and re-renders it as VALIDATED with editing hidden', async () => {
    setAdminUser()
    invoiceToReturn = makeInvoice()
    const router = makeRouter()
    router.push({ name: 'invoice-detail', params: { id: '3' } })
    await router.isReady()
    const wrapper = mount(InvoiceDetail, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('button#validate-invoice').trigger('click')
    await flushPromises()

    expect(validateInvoice).toHaveBeenCalledWith(3)
    expect(wrapper.text()).toContain('Validée')
    expect(wrapper.find('#total_amount').exists()).toBe(false)
    expect(wrapper.find('button#correct-invoice').exists()).toBe(true)
  })

  it('submits an audited correction and shows it in the history', async () => {
    setAdminUser()
    invoiceToReturn = makeInvoice({ status: 'VALIDATED' })
    const router = makeRouter()
    router.push({ name: 'invoice-detail', params: { id: '3' } })
    await router.isReady()
    const wrapper = mount(InvoiceDetail, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('button#correct-invoice').trigger('click')
    await flushPromises()

    await wrapper.find('#correction_field').setValue('unit_selling_price')
    await wrapper.find('#correction_new_value').setValue('605.0000')
    await wrapper.find('#correction_reason').setValue('Erreur de saisie contractuelle')
    await wrapper.find('#correction-form').trigger('submit.prevent')
    await flushPromises()

    expect(correctInvoice).toHaveBeenCalledWith(
      3,
      'unit_selling_price',
      '605.0000',
      'Erreur de saisie contractuelle',
    )
    expect(wrapper.text()).toContain('Erreur de saisie contractuelle')
    expect(wrapper.text()).toContain('unit_selling_price')
  })
})
