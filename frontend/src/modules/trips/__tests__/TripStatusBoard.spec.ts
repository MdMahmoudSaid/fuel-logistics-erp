import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import TripStatusBoard from '../TripStatusBoard.vue'
import type { Trip } from '../types'
import { i18n } from '@/i18n'

const todayIso = new Date().toISOString().slice(0, 10)

const trips: Trip[] = [
  {
    id: 1,
    reference: 'TRIP-STOCK',
    truck: 1,
    truck_detail: null,
    transporter: 1,
    transporter_detail: { id: 1, name: 'Transporteur 1' },
    driver: null,
    driver_detail: null,
    supplier: 1,
    supplier_detail: { id: 1, name: 'Supplier 1' },
    supplier_order: 1,
    cession_letter: 1,
    cession_letter_detail: {
      id: 1,
      reference: 'CES-001',
      supplier_order: 1,
      authorized_quantity: '45000.00',
      issue_date: todayIso,
      status: 'ACTIVE',
      notes: '',
      created_by: null,
      created_by_detail: null,
      loaded_quantity: '30000.00',
      remaining_quantity: '15000.00',
      documents: [],
      created_at: todayIso,
      updated_at: todayIso,
    },
    cession_letter_truck_load_count: 3,
    product: 1,
    product_detail: { id: 1, name: 'Gasoil', code: 'GO' },
    quantity_loaded: '10000.00',
    client: null,
    client_detail: null,
    customer_order: null,
    destination_type: 'COMPANY_STOCK',
    loading_date: todayIso,
    bl_reference: 'BL-1',
    status: 'ARRIVED_AT_COMPANY_STOCK',
    notes: '',
    created_by: null,
    created_by_detail: null,
    created_at: todayIso,
    updated_at: todayIso,
  },
  {
    id: 2,
    reference: 'TRIP-TRANSIT',
    truck: 2,
    truck_detail: null,
    transporter: 1,
    transporter_detail: { id: 1, name: 'Transporteur 1' },
    driver: null,
    driver_detail: null,
    supplier: 1,
    supplier_detail: { id: 1, name: 'Supplier 1' },
    supplier_order: 1,
    cession_letter: 1,
    cession_letter_truck_load_count: 1,
    product: 1,
    product_detail: { id: 1, name: 'Gasoil', code: 'GO' },
    quantity_loaded: '5000.00',
    client: null,
    client_detail: null,
    customer_order: null,
    destination_type: 'COMPANY_STOCK',
    loading_date: todayIso,
    bl_reference: 'BL-2',
    status: 'IN_TRANSIT',
    notes: '',
    created_by: null,
    created_by_detail: null,
    created_at: todayIso,
    updated_at: todayIso,
  },
  {
    id: 3,
    reference: 'TRIP-CANCELLED',
    truck: 3,
    truck_detail: null,
    transporter: 1,
    transporter_detail: { id: 1, name: 'Transporteur 1' },
    driver: null,
    driver_detail: null,
    supplier: 1,
    supplier_detail: { id: 1, name: 'Supplier 1' },
    supplier_order: 1,
    cession_letter: 1,
    cession_letter_truck_load_count: 1,
    product: 1,
    product_detail: { id: 1, name: 'Gasoil', code: 'GO' },
    quantity_loaded: '8000.00',
    client: null,
    client_detail: null,
    customer_order: null,
    destination_type: 'COMPANY_STOCK',
    loading_date: todayIso,
    bl_reference: 'BL-3',
    status: 'CANCELLED',
    notes: '',
    created_by: null,
    created_by_detail: null,
    created_at: todayIso,
    updated_at: todayIso,
  },
]

const tripList = vi.fn(async () => ({
  count: trips.length,
  next: null,
  previous: null,
  results: trips,
}))

vi.mock('../api', () => ({
  tripResource: { list: (...args: unknown[]) => tripList(...(args as [])) },
}))

function makeRouter() {
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/trips', name: 'trips', component: TripStatusBoard },
      { path: '/company-stock', name: 'company-stock', component: TripStatusBoard },
      { path: '/trips/new', name: 'trip-new', component: { template: '<div />' } },
      { path: '/trips/:id', name: 'trip-detail', component: { template: '<div />' } },
    ],
  })
}

async function mountAt(path: string) {
  const router = makeRouter()
  await router.push(path)
  await router.isReady()
  const wrapper = mount(TripStatusBoard, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('TripStatusBoard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    i18n.global.locale.value = 'fr'
  })

  it('opens /trips with the Tous filter active by default', async () => {
    const { wrapper } = await mountAt('/trips')

    const allChip = wrapper.findAll('button').find((button) => button.text() === 'Tous')
    const stockChip = wrapper
      .findAll('button')
      .find((button) => button.text() === 'Stock entreprise')

    expect(allChip?.classes()).toContain('bg-orange-tint')
    expect(stockChip?.classes()).not.toContain('bg-orange-tint')
    expect(wrapper.text()).toContain('TRIP-STOCK')
    expect(wrapper.text()).toContain('TRIP-TRANSIT')
    // "Tous" = active trips only - a cancelled trip stays out of it (bug
    // fix, 2026-09-03 recette manuelle: it now has its own "Annulés" tab
    // instead of being simply unreachable).
    expect(wrapper.text()).not.toContain('TRIP-CANCELLED')
  })

  it('shows only cancelled trips under the Annulés filter', async () => {
    const { wrapper } = await mountAt('/trips')

    const cancelledChip = wrapper.findAll('button').find((button) => button.text() === 'Annulés')
    expect(cancelledChip).toBeTruthy()
    await cancelledChip!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('TRIP-CANCELLED')
    expect(wrapper.text()).not.toContain('TRIP-STOCK')
    expect(wrapper.text()).not.toContain('TRIP-TRANSIT')
  })

  it('opens /company-stock with only company stock trips visible', async () => {
    const { wrapper } = await mountAt('/company-stock')

    const stockChip = wrapper
      .findAll('button')
      .find((button) => button.text() === 'Stock entreprise')

    expect(stockChip?.classes()).toContain('bg-orange-tint')
    expect(wrapper.text()).toContain('TRIP-STOCK')
    expect(wrapper.text()).not.toContain('TRIP-TRANSIT')
  })

  it('updates the active filter when navigating from /trips to /company-stock without remounting', async () => {
    const { wrapper, router } = await mountAt('/trips')

    await router.push('/company-stock')
    await flushPromises()

    const allChip = wrapper.findAll('button').find((button) => button.text() === 'Tous')
    const stockChip = wrapper
      .findAll('button')
      .find((button) => button.text() === 'Stock entreprise')

    expect(allChip?.classes()).not.toContain('bg-orange-tint')
    expect(stockChip?.classes()).toContain('bg-orange-tint')
    expect(wrapper.text()).toContain('TRIP-STOCK')
    expect(wrapper.text()).not.toContain('TRIP-TRANSIT')
  })

  it('updates the active filter when navigating from /company-stock to /trips without remounting', async () => {
    const { wrapper, router } = await mountAt('/company-stock')

    await router.push('/trips')
    await flushPromises()

    const allChip = wrapper.findAll('button').find((button) => button.text() === 'Tous')
    const stockChip = wrapper
      .findAll('button')
      .find((button) => button.text() === 'Stock entreprise')

    expect(allChip?.classes()).toContain('bg-orange-tint')
    expect(stockChip?.classes()).not.toContain('bg-orange-tint')
    expect(wrapper.text()).toContain('TRIP-STOCK')
    expect(wrapper.text()).toContain('TRIP-TRANSIT')
  })

  it('shows the cession letter reference and this truck\'s load count under it', async () => {
    const { wrapper } = await mountAt('/trips')

    expect(wrapper.text()).toContain('CES-001')
    expect(wrapper.text()).toContain('3 chargement(s) de ce camion')
  })
})
