import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import TripForm from '../TripForm.vue'
import { useAuthStore } from '@/stores/auth'
import type { CessionLetter, SupplierOrder } from '@/modules/purchasing/types'

const CESSION: CessionLetter = {
  id: 9,
  reference: 'CL-009',
  supplier_order: 5,
  authorized_quantity: '45000.00',
  issue_date: '2026-08-18',
  status: 'ACTIVE',
  notes: '',
  created_by: 1,
  created_by_detail: null,
  loaded_quantity: '0.00',
  remaining_quantity: '45000.00',
  documents: [],
  created_at: '',
  updated_at: '',
}

const SUPPLIER_ORDER: SupplierOrder = {
  id: 5,
  reference: 'SO-005',
  supplier: 2,
  supplier_detail: { id: 2, name: 'Total', company_name: '', country: 'Senegal' },
  product: 3,
  product_detail: { id: 3, name: 'Gasoil', code: 'gasoil' },
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
  reliquat: '55000.00',
  loaded_quantity: '0.00',
  documents: [],
  cessions: [],
  created_at: '',
  updated_at: '',
}

const AVAILABLE_TRUCK = {
  id: 1,
  internal_id: 'TRK-001',
  tractor_registration: 'AA-001',
  tanker_registration: 'BB-001',
  capacity_litres: '45000.00',
  status: 'AVAILABLE',
  owner_transporter: null,
  default_driver: null,
}
const BUSY_TRUCK = {
  id: 2,
  internal_id: 'TRK-002',
  tractor_registration: 'AA-002',
  tanker_registration: 'BB-002',
  capacity_litres: '45000.00',
  status: 'ON_TRIP',
  owner_transporter: null,
  default_driver: null,
}

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

vi.mock('@/api/resource', () => ({
  createResourceApi: vi.fn((basePath: string) => ({
    list: vi.fn(async (params?: Record<string, unknown>) => {
      if (basePath === '/trucks/') {
        const trucks = params?.status ? [AVAILABLE_TRUCK] : [AVAILABLE_TRUCK, BUSY_TRUCK]
        return paginated(trucks)
      }
      return paginated([])
    }),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  })),
}))

vi.mock('@/modules/purchasing/api', () => ({
  cessionLetterResource: { list: vi.fn(async () => paginated([CESSION])) },
  supplierOrderResource: { get: vi.fn(async () => SUPPLIER_ORDER) },
}))

vi.mock('@/modules/sales/api', () => ({
  customerOrderResource: { list: vi.fn(async () => paginated([])) },
}))

const createTrip = vi.fn(async (payload: Record<string, unknown>) => ({ id: 42, ...payload }))
vi.mock('../api', () => ({
  tripResource: { create: (payload: Record<string, unknown>) => createTrip(payload) },
}))

function makeRouter() {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/trips/new', name: 'trip-new', component: TripForm },
      { path: '/trips/:id', name: 'trip-detail', component: stub },
    ],
  })
  router.push({ name: 'trip-new' })
  return router
}

describe('TripForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('defaults the truck picker to AVAILABLE trucks only', async () => {
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(TripForm, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('TRK-001')
    expect(wrapper.text()).not.toContain('TRK-002')
  })

  it('hides the occupied-trucks override from a non-Admin user', async () => {
    const router = makeRouter()
    await router.isReady()
    const auth = useAuthStore()
    auth.user = {
      id: 1,
      phone: '+22212345678',
      email: 'ops@example.com',
      full_name: 'Ops',
      role: 2,
      role_detail: { id: 2, name: 'Operations', permissions: {} },
    }
    const wrapper = mount(TripForm, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.find('#show_busy').exists()).toBe(false)
  })

  it('shows the occupied-trucks override to an Admin and reveals busy trucks when enabled', async () => {
    const router = makeRouter()
    await router.isReady()
    const auth = useAuthStore()
    auth.user = {
      id: 1,
      phone: '+22212345678',
      email: 'admin@example.com',
      full_name: 'Admin',
      role: 1,
      role_detail: { id: 1, name: 'Admin', permissions: {} },
    }
    const wrapper = mount(TripForm, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.find('#show_busy').exists()).toBe(true)
    await wrapper.find('#show_busy').setValue(true)
    await flushPromises()

    expect(wrapper.text()).toContain('TRK-002')
  })

  it('warns when the requested quantity exceeds the cession remaining balance', async () => {
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(TripForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#cession_letter').setValue('9')
    await flushPromises()

    await wrapper.find('#quantity_loaded').setValue('50000')
    await flushPromises()

    expect(wrapper.text()).toContain("Dépasse la quantité restante de la cession")
  })

  it('sends force=true only when the busy-truck override was used', async () => {
    const router = makeRouter()
    await router.isReady()
    const auth = useAuthStore()
    auth.user = {
      id: 1,
      phone: '+22212345678',
      email: 'admin@example.com',
      full_name: 'Admin',
      role: 1,
      role_detail: { id: 1, name: 'Admin', permissions: {} },
    }
    const wrapper = mount(TripForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#cession_letter').setValue('9')
    await flushPromises()
    await wrapper.find('#truck').setValue('1')
    await wrapper.find('#transporter').setValue('') // no transporters seeded; leave as-is
    await wrapper.find('#quantity_loaded').setValue('20000')
    await wrapper.find('#loading_date').setValue('2026-08-18')
    await wrapper.find('#bl_reference').setValue('BL-001')

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(createTrip).toHaveBeenCalledWith(expect.objectContaining({ force: false }))
  })

  it('surfaces a per-field 400 error under the matching field instead of the first one found', async () => {
    createTrip.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { truck: ['Autre erreur.'], bl_reference: ['Cette référence existe déjà.'] },
      },
    })
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(TripForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#cession_letter').setValue('9')
    await flushPromises()
    await wrapper.find('#truck').setValue('1')
    await wrapper.find('#transporter').setValue('') // no transporters seeded; leave as-is
    await wrapper.find('#quantity_loaded').setValue('20000')
    await wrapper.find('#loading_date').setValue('2026-08-18')
    await wrapper.find('#bl_reference').setValue('BL-DUP')

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    const blContainer = wrapper.find('#bl_reference').element.closest('div')
    expect(blContainer?.textContent).toContain('Cette référence existe déjà.')

    const truckContainer = wrapper.find('#truck').element.closest('div')
    expect(truckContainer?.textContent).toContain('Autre erreur.')
  })
})
