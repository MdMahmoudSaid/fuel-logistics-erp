import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import TripDetail from '../TripDetail.vue'
import { useAuthStore } from '@/stores/auth'
import type { Trip, TripMargin } from '../types'
import type { Expense } from '@/modules/finance/types'

function makeTrip(overrides: Partial<Trip> = {}): Trip {
  return {
    id: 9,
    reference: 'TRIP-009',
    truck: 1,
    truck_detail: {
      id: 1,
      internal_id: 'TRK-1',
      tractor_registration: 'AA-111',
      tanker_registration: 'BB-222',
      capacity_litres: '45000.00',
      status: 'ON_TRIP',
      owner_transporter: null,
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
    product: 6,
    product_detail: { id: 6, name: 'Gasoil', code: 'gasoil' },
    quantity_loaded: '45000.00',
    client: null,
    client_detail: null,
    customer_order: null,
    loading_date: '2026-08-18',
    bl_reference: 'BL-1',
    status: 'IN_TRANSIT',
    notes: '',
    created_by: 1,
    created_by_detail: null,
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

const tripToReturn = makeTrip()
const tripResourceGet = vi.fn(async (_id: number) => tripToReturn)
const fetchTripHistory = vi.fn(async (_id: number) => [])
let marginToReturn: TripMargin = { available: false }
const fetchTripMargin = vi.fn(async (_id: number) => marginToReturn)
vi.mock('../api', () => ({
  tripResource: { get: (id: number) => tripResourceGet(id) },
  fetchTripHistory: (id: number) => fetchTripHistory(id),
  fetchTripMargin: (id: number) => fetchTripMargin(id),
  postTripStatus: vi.fn(),
}))

let expensesToReturn: Expense[] = []
const expenseList = vi.fn(async (_params: Record<string, unknown>) => ({
  count: expensesToReturn.length,
  next: null,
  previous: null,
  results: expensesToReturn,
}))
// ExpenseForm.vue (mounted for real inside TripDetail's "Add expense"
// overlay) also imports fetchAllocatableTypes from this module.
vi.mock('@/modules/finance/api', () => ({
  expenseResource: { list: (params: Record<string, unknown>) => expenseList(params) },
  fetchAllocatableTypes: vi.fn(async () => ({
    trip: 12,
    truck: 13,
    customer: 14,
    supplier: 15,
    transporter: 16,
  })),
  fetchCustomerLedger: vi.fn(),
  recordIndirectExpense: vi.fn(),
}))

// ExpenseForm.vue also lists customers (for the "paid by customer" toggle)
// via this generic factory - stub it out so no real HTTP call fires.
vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({
    list: async () => ({ count: 0, next: null, previous: null, results: [] }),
  }),
}))

vi.mock('@/modules/reports/api', () => ({
  fetchReport: vi.fn(async () => ({ rows: [] })),
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
      { path: '/trips', name: 'trips', component: stub },
      { path: '/trips/:id', name: 'trip-detail', component: TripDetail },
      { path: '/transporters/:id/ledger', name: 'transporter-ledger', component: stub },
      { path: '/customer-orders/:id', name: 'customer-order-detail', component: stub },
    ],
  })
  return router
}

function makeExpense(overrides: Partial<Expense> = {}): Expense {
  return {
    id: 1,
    category: 'customs',
    amount: '150000.00',
    calculation_method: 'FIXED',
    date: '2026-08-20',
    status: 'UNPAID',
    paid_by_customer_directly: false,
    notes: '',
    allocations_detail: [
      {
        id: 1,
        expense: 1,
        content_type: 12,
        content_type_name: 'trip',
        object_id: 9,
        content_object_repr: 'TRIP-009',
        allocated_amount: '90000.00',
        created_at: '',
      },
    ],
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

describe('TripDetail expenses section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    tripResourceGet.mockResolvedValue(tripToReturn)
    fetchTripHistory.mockResolvedValue([])
    expensesToReturn = []
    marginToReturn = { available: false }
  })

  async function mountAt(tripId = '9') {
    const router = makeRouter()
    router.push({ name: 'trip-detail', params: { id: tripId } })
    await router.isReady()
    const wrapper = mount(TripDetail, { global: { plugins: [router] } })
    await flushPromises()
    return wrapper
  }

  it('shows the trip-specific allocated amount, not the expense total', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    expensesToReturn = [makeExpense()]

    const wrapper = await mountAt()

    expect(expenseList).toHaveBeenCalledWith({ trip: 9 })
    expect(wrapper.text()).toContain('90,000')
    expect(wrapper.text()).not.toContain('150,000')
  })

  it('shows an empty state when the trip has no expenses', async () => {
    setUser({ operations: ['view'], finance: ['view'] })

    const wrapper = await mountAt()

    expect(wrapper.text()).toContain('Aucun frais enregistré pour ce trajet.')
  })

  it('hides "Add expense" without finance create permission', async () => {
    setUser({ operations: ['view'], finance: ['view'] })

    const wrapper = await mountAt()

    expect(
      wrapper.findAll('button').find((b) => b.text().includes('Ajouter un frais')),
    ).toBeUndefined()
  })

  it('opens the expense form pre-seeded with this trip when "Add expense" is clicked', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })

    const wrapper = await mountAt()

    const addButton = wrapper.findAll('button').find((b) => b.text().includes('Ajouter un frais'))
    expect(addButton).toBeDefined()
    await addButton!.trigger('click')

    expect(wrapper.text()).toContain('TRIP-009')
  })

  it('shows the "not yet available" message before the trip has a Sale', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    marginToReturn = { available: false }

    const wrapper = await mountAt()

    expect(fetchTripMargin).toHaveBeenCalledWith(9)
    expect(wrapper.text()).toContain('Disponible une fois la livraison confirmée.')
  })

  it('shows the revenue/cost breakdown once available, including a per-category expense line', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    marginToReturn = {
      available: true,
      revenue: '29152500.00',
      fuel_purchase_cost: '27000000.00',
      transport_cost: '500000.00',
      expenses_by_category: { customs: '90000.00' },
      total_expenses: '90000.00',
      margin: '1562500.00',
      unit_cost: '611.11',
      unit_profit: '38.89',
    }

    const wrapper = await mountAt()

    const text = wrapper.text()
    expect(text).toContain('29,152,500')
    expect(text).toContain('-27,000,000')
    expect(text).toContain('-500,000')
    expect(text).toContain('-90,000')
    expect(text).toContain('1,562,500')
  })

  it('highlights a negative margin', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    marginToReturn = {
      available: true,
      revenue: '1000.00',
      fuel_purchase_cost: '2000.00',
      transport_cost: '0.00',
      expenses_by_category: {},
      total_expenses: '0.00',
      margin: '-1000.00',
      unit_cost: '2000.00',
      unit_profit: '-1500.00',
    }

    const wrapper = await mountAt()

    const marginValue = wrapper.findAll('dd').find((dd) => dd.text().includes('-1,000'))
    expect(marginValue?.find('span').classes()).toContain('text-critique')
  })

  it('shows the unit cost and unit profit lines from the margin breakdown', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    marginToReturn = {
      available: true,
      revenue: '29152500.00',
      fuel_purchase_cost: '27000000.00',
      transport_cost: '500000.00',
      expenses_by_category: {},
      total_expenses: '0.00',
      margin: '1652500.00',
      unit_cost: '611.11',
      unit_profit: '38.89',
    }

    const wrapper = await mountAt()

    const text = wrapper.text()
    expect(text).toContain('611.11')
    expect(text).toContain('38.89')
  })
})
