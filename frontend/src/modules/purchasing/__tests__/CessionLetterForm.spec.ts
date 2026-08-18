import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import CessionLetterForm from '../CessionLetterForm.vue'
import type { SupplierOrder } from '../types'

// Order: 100,000 L purchased, 60,000 L already allocated to other cessions
// (reliquat = 40,000 L). This is exactly the spec §6 worked example.
const ORDER: SupplierOrder = {
  id: 5,
  reference: 'SO-005',
  supplier: 1,
  supplier_detail: { id: 1, name: 'Total', company_name: '', country: 'Senegal' },
  product: 1,
  product_detail: { id: 1, name: 'Gasoil', code: 'gasoil' },
  purchase_date: '2026-08-18',
  quantity_litres: '100000.00',
  unit_price: '600.0000',
  currency: 'XOF',
  total_amount: '60000000.00',
  optional_costs: null,
  notes: '',
  status: 'CONFIRMED',
  created_by: 1,
  created_by_detail: null,
  reliquat: '40000.00',
  loaded_quantity: '0.00',
  documents: [],
  cessions: [],
  created_at: '',
  updated_at: '',
}

vi.mock('../api', () => ({
  supplierOrderResource: { get: vi.fn(async () => ORDER) },
  cessionLetterResource: { get: vi.fn(), create: vi.fn(), update: vi.fn(), list: vi.fn() },
  uploadDocument: vi.fn(),
}))

function makeRouter(query: Record<string, string> = {}) {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/cession-letters/new', name: 'cession-letter-new', component: CessionLetterForm },
      { path: '/cession-letters/:id', name: 'cession-letter-detail', component: stub },
      { path: '/supplier-orders', name: 'supplier-orders', component: stub },
    ],
  })
  router.push({ name: 'cession-letter-new', query })
  return router
}

describe('CessionLetterForm live allocation bar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the remaining reliquat and no warning for a request within the limit', async () => {
    const router = makeRouter({ supplier_order: '5' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#authorized_quantity').setValue('30000')
    await flushPromises()

    expect(wrapper.text()).toContain('10,000 L would remain available')
    expect(wrapper.text()).not.toContain('Exceeds available reliquat')
  })

  it('warns immediately when the requested quantity exceeds the reliquat', async () => {
    const router = makeRouter({ supplier_order: '5' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    // spec §6 worked example: 40,000 L remaining, requesting 45,000 L must warn.
    await wrapper.find('#authorized_quantity').setValue('45000')
    await flushPromises()

    expect(wrapper.text()).toContain('Exceeds available reliquat by 5,000 L')
  })
})
