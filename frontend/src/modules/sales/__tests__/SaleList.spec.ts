import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import SaleList from '../SaleList.vue'
import { useAuthStore } from '@/stores/auth'
import type { Trip } from '@/modules/trips/types'

function makeTrip(overrides: Partial<Trip> = {}): Trip {
  return {
    id: 21,
    reference: 'TRIP-021',
    truck: 1,
    truck_detail: {
      id: 1,
      internal_id: 'TRK-1',
      tractor_registration: 'AA-111',
      tanker_registration: 'BB-222',
      capacity_litres: '45000.00',
      status: 'AVAILABLE',
      ownership_type: 'EXTERNAL',
      owner_transporter: 2,
      default_driver: null,
    },
    transporter: 2,
    transporter_detail: { id: 2, name: 'Trans SA' },
    driver: null,
    driver_detail: null,
    supplier: 3,
    supplier_detail: { id: 3, name: 'Total' },
    supplier_order: 4,
    cession_letter: 5,
    cession_letter_detail: null,
    cession_letter_truck_load_count: 1,
    delivery_control_detail: null,
    product: 6,
    product_detail: { id: 6, name: 'Gasoil', code: 'gasoil' },
    quantity_loaded: '45000.00',
    client: null,
    client_detail: null,
    customer_order: null,
    destination_type: 'COMPANY_STOCK',
    loading_date: '2026-08-18',
    bl_reference: 'BL-1',
    status: 'STOCKED',
    notes: '',
    created_by: 1,
    created_by_detail: null,
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

const tripListMock = vi.fn(async () => ({
  count: 1,
  next: null,
  previous: null,
  results: [makeTrip()],
}))
const assignTripCustomer = vi.fn(async (_tripId: number, _customerId: number) => makeTrip())

vi.mock('@/modules/trips/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/trips/api')>()
  return {
    ...actual,
    tripResource: { ...actual.tripResource, list: () => tripListMock() },
    assignTripCustomer: (tripId: number, customerId: number) =>
      assignTripCustomer(tripId, customerId),
  }
})

vi.mock('@/api/resource', () => ({
  createResourceApi: (basePath: string) => ({
    list: async () => {
      if (basePath === '/customers/') {
        return {
          count: 1,
          next: null,
          previous: null,
          results: [{ id: 30, name: 'Client Test Mohamed' }],
        }
      }
      return { count: 0, next: null, previous: null, results: [] }
    },
  }),
}))

function setUser(permissions: Record<string, string[]>) {
  const auth = useAuthStore()
  auth.user = {
    id: 1,
    phone: '+22212345678',
    email: 'admin@example.com',
    full_name: 'Admin',
    role: 1,
    role_detail: { id: 1, name: 'Admin', permissions },
  }
}

function makeRouter() {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/sales', name: 'sales', component: SaleList },
      { path: '/trips/:id', name: 'trip-detail', component: stub },
    ],
  })
  return router
}

async function mountAt(permissions: Record<string, string[]> = { operations: ['view', 'edit'] }) {
  setUser(permissions)
  const router = makeRouter()
  router.push('/sales')
  await router.isReady()
  const wrapper = mount(SaleList, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('SaleList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('shows the "assign a customer" action only with the assign_customer permission tier', async () => {
    const { wrapper } = await mountAt({ operations: ['view'] })
    expect(
      wrapper.findAll('button').find((b) => b.text() === 'Attribuer un client'),
    ).toBeUndefined()
  })

  it('opens the picker with only unassigned company-stock trips', async () => {
    tripListMock.mockResolvedValueOnce({
      count: 2,
      next: null,
      previous: null,
      results: [
        makeTrip({ id: 21, reference: 'TRIP-021' }),
        makeTrip({ id: 22, reference: 'TRIP-022', client: 40 }), // already has a client
      ],
    })
    const { wrapper } = await mountAt()

    const openButton = wrapper.findAll('button').find((b) => b.text() === 'Attribuer un client')
    await openButton!.trigger('click')
    await flushPromises()

    const rows = wrapper.findAll('[data-test="eligible-trip-row"]')
    expect(rows).toHaveLength(1)
    expect(rows[0]!.text()).toContain('TRIP-021')
    expect(rows[0]!.text()).toContain('AA-111 / BB-222')
  })

  it('assigns the selected trip to a customer and navigates to the trip detail page', async () => {
    const { wrapper, router } = await mountAt()
    const pushSpy = vi.spyOn(router, 'push')

    const openButton = wrapper.findAll('button').find((b) => b.text() === 'Attribuer un client')
    await openButton!.trigger('click')
    await flushPromises()

    await wrapper.find('[data-test="eligible-trip-row"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('TRIP-021')

    const select = wrapper.findComponent({ name: 'UiSearchableSelect' })
    await select.vm.$emit('update:modelValue', '30')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(assignTripCustomer).toHaveBeenCalledWith(21, 30)
    expect(pushSpy).toHaveBeenCalledWith({ name: 'trip-detail', params: { id: 21 } })
  })
})
