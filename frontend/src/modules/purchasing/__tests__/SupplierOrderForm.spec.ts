import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import SupplierOrderForm from '../SupplierOrderForm.vue'

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

vi.mock('@/api/resource', () => ({
  createResourceApi: vi.fn(() => ({
    list: vi.fn(async () => paginated([])),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  })),
}))

const create = vi.fn()
const fetchNextSupplierOrderReference = vi.fn(async () => 'ACH-202608-0007')
vi.mock('../api', () => ({
  supplierOrderResource: {
    get: vi.fn(),
    create: (payload: Record<string, unknown>) => create(payload),
    update: vi.fn(),
  },
  uploadDocument: vi.fn(),
  fetchNextSupplierOrderReference: () => fetchNextSupplierOrderReference(),
}))

function makeRouter() {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/supplier-orders/new', name: 'supplier-order-new', component: SupplierOrderForm },
      { path: '/supplier-orders/:id', name: 'supplier-order-detail', component: stub },
      { path: '/supplier-orders', name: 'supplier-orders', component: stub },
    ],
  })
  router.push({ name: 'supplier-order-new' })
  return router
}

describe('SupplierOrderForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('pre-fills the reference as a read-only, server-generated value', async () => {
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(SupplierOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    const input = wrapper.find<HTMLInputElement>('#reference')
    expect(input.attributes('autocomplete')).toBe('off')
    expect(input.attributes('disabled')).toBeDefined()
    expect(input.element.value).toBe('ACH-202608-0007')
    expect(fetchNextSupplierOrderReference).toHaveBeenCalled()
  })

  it('surfaces a backend uniqueness error under the reference field instead of a generic message', async () => {
    create.mockRejectedValueOnce({
      response: { status: 400, data: { reference: ['Cette référence existe déjà.'] } },
    })
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(SupplierOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#supplier').setValue('')
    await wrapper.find('#purchase_date').setValue('2026-08-20')
    await wrapper.find('#quantity_litres').setValue('1000')
    await wrapper.find('#unit_price').setValue('600')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Cette référence existe déjà.')
    expect(wrapper.text()).not.toContain("Impossible d'enregistrer")
  })
})
