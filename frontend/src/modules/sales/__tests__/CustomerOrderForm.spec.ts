import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import CustomerOrderForm from '../CustomerOrderForm.vue'
import type { CustomerOrder } from '../types'

function makeOrder(overrides: Partial<CustomerOrder> = {}): CustomerOrder {
  return {
    id: 7,
    customer: 1,
    customer_detail: { id: 1, name: 'Client X', company_name: '' },
    product: 1,
    product_detail: { id: 1, name: 'Gasoil', code: 'gasoil' },
    quantity_ordered: '450000.00',
    expected_price: null,
    status: 'CONFIRMED',
    notes: '',
    assigned_quantity: '270000.00',
    loaded_quantity: '180000.00',
    delivered_quantity: '90000.00',
    remaining_quantity: '360000.00',
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

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

let orderToReturn: CustomerOrder
vi.mock('../api', () => ({
  customerOrderResource: {
    get: vi.fn(async () => orderToReturn),
    update: vi.fn(),
    create: vi.fn(),
  },
  fetchCustomerOrderTrips: vi.fn(async () => []),
}))

function makeRouter() {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/customer-orders/new', name: 'customer-order-new', component: stub },
      { path: '/customer-orders/:id', name: 'customer-order-detail', component: CustomerOrderForm },
      { path: '/customer-orders', name: 'customer-orders', component: stub },
      { path: '/trips/new', name: 'trip-new', component: stub },
      { path: '/trips/:id', name: 'trip-detail', component: stub },
    ],
  })
  return router
}

describe('CustomerOrderForm progress bar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the assigned/loaded/delivered quantities against the ordered total', async () => {
    orderToReturn = makeOrder()
    const router = makeRouter()
    router.push({ name: 'customer-order-detail', params: { id: '7' } })
    await router.isReady()
    const wrapper = mount(CustomerOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('270,000 L')
    expect(wrapper.text()).toContain('180,000 L')
    expect(wrapper.text()).toContain('90,000 L')
    expect(wrapper.text()).toContain('Commandé 450,000 L')
    expect(wrapper.text()).toContain('Restant 360,000 L')
  })
})

describe('CustomerOrderForm status guard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lets a manual status (CONFIRMED) be edited directly', async () => {
    orderToReturn = makeOrder({ status: 'CONFIRMED' })
    const router = makeRouter()
    router.push({ name: 'customer-order-detail', params: { id: '7' } })
    await router.isReady()
    const wrapper = mount(CustomerOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.find('#status').exists()).toBe(true)
  })

  it('shows a derived status (PARTIALLY_ASSIGNED) as read-only, not an editable select', async () => {
    orderToReturn = makeOrder({ status: 'PARTIALLY_ASSIGNED' })
    const router = makeRouter()
    router.push({ name: 'customer-order-detail', params: { id: '7' } })
    await router.isReady()
    const wrapper = mount(CustomerOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.find('#status').exists()).toBe(false)
    expect(wrapper.text()).toContain('Partiellement affectée')
    expect(wrapper.text()).toContain('calculé à partir de la progression des trajets')
  })
})
