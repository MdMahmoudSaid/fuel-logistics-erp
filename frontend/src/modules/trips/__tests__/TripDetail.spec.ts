import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import TripDetail from '../TripDetail.vue'
import { useAuthStore } from '@/stores/auth'
import type { Trip, TripMargin } from '../types'
import type { Expense, TransportPayment } from '@/modules/finance/types'

// Bug fix (2026-09-18): destructive actions now go through the app's own
// popup instead of window.confirm() - see useConfirmDialog. Defaults to
// "confirmed"; tests exercising the decline path override with
// mockResolvedValueOnce(false).
const confirmDialogMock = vi.fn(async (_message: string) => true)
vi.mock('@/composables/useConfirmDialog', () => ({
  confirmDialog: (message: string) => confirmDialogMock(message),
}))

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
    cession_letter_detail: {
      id: 5,
      reference: 'CES-005',
      supplier_order: 4,
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
    },
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
const postTripStatus = vi.fn(
  async (
    _id: number,
    _status: string,
    _notes = '',
  ): Promise<Trip & { traversed_statuses?: string[] }> => tripToReturn,
)
let allowedStatusesToReturn: string[] = ['IN_TRANSIT', 'BLOCKED', 'CANCELLED']
const fetchAllowedTripStatuses = vi.fn(async (_id: number) => allowedStatusesToReturn)
const postDeliveryControl = vi.fn(async (_tripId: number, payload: Record<string, unknown>) => ({
  id: 1,
  trip: 9,
  loaded_quantity: '45000.00',
  received_quantity: '45000.00',
  loss_quantity: '0.00',
  chargeable_loss_quantity: '0.00',
  tolerance_quantity: '100.00',
  control_date: payload.control_date,
  controller: 1,
  controller_detail: null,
  method: payload.method,
  document: null,
  notes: '',
  anomaly_confirmed_by: null,
  anomaly_confirmed_by_detail: null,
  anomaly_confirmed_at: null,
  created_at: '',
  updated_at: '',
}))
const postClientVerification = vi.fn(async (_tripId: number, payload: Record<string, unknown>) => ({
  id: 1,
  trip: 9,
  loaded_quantity: '45000.00',
  received_quantity: payload.received_quantity,
  loss_quantity: '150.00',
  chargeable_loss_quantity: '50.00',
  tolerance_quantity: '100.00',
  control_date: '2026-08-18',
  controller: 1,
  controller_detail: null,
  method: 'MANUAL_GAUGE',
  document: null,
  notes: '',
  anomaly_confirmed_by: null,
  anomaly_confirmed_by_detail: null,
  anomaly_confirmed_at: null,
  verified_at: payload.verified_at,
  verification_corrections: [],
  created_at: '',
  updated_at: '',
}))
const postClientVerificationCorrection = vi.fn(
  async (_tripId: number, payload: Record<string, unknown>) => ({
    id: 1,
    trip: 9,
    loaded_quantity: '45000.00',
    received_quantity: payload.received_quantity,
    loss_quantity: '100.00',
    chargeable_loss_quantity: '0.00',
    tolerance_quantity: '100.00',
    control_date: '2026-08-18',
    controller: 1,
    controller_detail: null,
    method: 'MANUAL_GAUGE',
    document: null,
    notes: '',
    anomaly_confirmed_by: null,
    anomaly_confirmed_by_detail: null,
    anomaly_confirmed_at: null,
    verified_at: '2026-08-19',
    verification_corrections: [
      {
        id: 1,
        previous_received_quantity: '100.00',
        new_received_quantity: payload.received_quantity,
        corrected_by: 1,
        corrected_by_detail: { id: 1, full_name: 'Admin', email: 'admin@example.com' },
        corrected_at: '2026-08-20T10:00:00Z',
        reason: payload.reason,
      },
    ],
    created_at: '',
    updated_at: '',
  }),
)
const fetchSuggestedSellingPrice = vi.fn(async () => '850.0000')
const fetchReport = vi.fn(async (_type: string, _params: Record<string, unknown>) => ({
  rows: [] as unknown[],
}))
const fetchTripCostBasis = vi.fn(async () => ({
  fuel_purchase_cost: '13500000.00',
  transport_cost: '13500000.00',
  expenses_by_category: {},
  total_expenses: '0.00',
  total_cost: '27000000.00',
  quantity: '45000.00',
  unit_cost: '600.0000',
  unit_components_per_litre: {
    supplier: '300.0000',
    commission_transporter: '300.0000',
    road_transit: '0.0000',
    transit: '0.0000',
    border: '0.0000',
    customs: '0.0000',
    loading: '0.0000',
    other: '0.0000',
  },
}))
vi.mock('../api', () => ({
  tripResource: { get: (id: number) => tripResourceGet(id) },
  fetchTripHistory: (id: number) => fetchTripHistory(id),
  fetchTripMargin: (id: number) => fetchTripMargin(id),
  fetchAllowedTripStatuses: (id: number) => fetchAllowedTripStatuses(id),
  postTripStatus: (id: number, status: string, notes?: string) => postTripStatus(id, status, notes),
  postDeliveryControl: (tripId: number, payload: Record<string, unknown>) =>
    postDeliveryControl(tripId, payload),
  postClientVerification: (tripId: number, payload: Record<string, unknown>) =>
    postClientVerification(tripId, payload),
  postClientVerificationCorrection: (tripId: number, payload: Record<string, unknown>) =>
    postClientVerificationCorrection(tripId, payload),
  fetchSuggestedSellingPrice: () => fetchSuggestedSellingPrice(),
  fetchTripCostBasis: () => fetchTripCostBasis(),
  assignTripCustomer: vi.fn(),
}))

vi.mock('@/modules/settings/api', () => ({
  fetchLossTolerance: vi.fn(async () => ({
    tolerance_litres: '100.00',
    updated_by: null,
    updated_by_detail: null,
    updated_at: null,
  })),
}))

function makeMargin(overrides: Partial<Extract<TripMargin, { available: true }>> = {}): TripMargin {
  return {
    available: true,
    quantity_loaded: '45000.00',
    quantity_invoiced: '44850.00',
    transporter_loss_quantity: '0.00',
    transporter_loss_indemnity: '0.00',
    company_absorbed_loss_quantity: '0.00',
    company_absorbed_loss_amount: '0.00',
    revenue: '29152500.00',
    fuel_purchase_cost: '27000000.00',
    transport_cost: '500000.00',
    expenses_by_category: {},
    total_expenses: '0.00',
    real_total_cost: '27500000.00',
    margin: '1652500.00',
    unit_cost: '611.11',
    unit_profit: '38.89',
    ...overrides,
  }
}

let expensesToReturn: Expense[] = []
let transportPaymentsToReturn: TransportPayment[] = []
const createExpense = vi.fn(async (_payload: Record<string, unknown>) => ({}))
const updateExpense = vi.fn(async (_id: number, _payload: Record<string, unknown>) => ({}))
const removeExpense = vi.fn(async (_id: number) => undefined)
const cancelExpense = vi.fn(async (_id: number) => ({}))
const createTransportPayment = vi.fn(async (_payload: Record<string, unknown>) => ({}))
const removeTransportPayment = vi.fn(async (_id: number) => undefined)
const cancelTransportPayment = vi.fn(async (_id: number) => ({}))
const correctTransportPayment = vi.fn(
  async (_id: number, _payload: Record<string, unknown>) => ({}),
)
const expenseList = vi.fn(async (_params: Record<string, unknown>) => ({
  count: expensesToReturn.length,
  next: null,
  previous: null,
  results: expensesToReturn,
}))
const transportPaymentList = vi.fn(async (_params: Record<string, unknown>) => ({
  count: transportPaymentsToReturn.length,
  next: null,
  previous: null,
  results: transportPaymentsToReturn,
}))
// ExpenseForm.vue (mounted for real inside TripDetail's "Add expense"
// overlay) also imports fetchAllocatableTypes from this module.
vi.mock('@/modules/finance/api', () => ({
  expenseResource: {
    list: (params: Record<string, unknown>) => expenseList(params),
    create: (payload: Record<string, unknown>) => createExpense(payload),
    update: (id: number, payload: Record<string, unknown>) => updateExpense(id, payload),
    remove: (id: number) => removeExpense(id),
  },
  cancelExpense: (id: number) => cancelExpense(id),
  cancelTransportPayment: (id: number) => cancelTransportPayment(id),
  correctTransportPayment: (id: number, payload: Record<string, unknown>) =>
    correctTransportPayment(id, payload),
  transportPaymentResource: {
    remove: (id: number) => removeTransportPayment(id),
    list: (params: Record<string, unknown>) => transportPaymentList(params),
    create: (payload: Record<string, unknown>) => createTransportPayment(payload),
  },
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
  fetchReport: (type: string, params: Record<string, unknown>) => fetchReport(type, params),
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

function makeTransportPayment(overrides: Partial<TransportPayment> = {}): TransportPayment {
  return {
    id: 8,
    trip: 9,
    trip_reference: 'TRIP-009',
    transporter: 2,
    transporter_detail: { id: 2, name: 'Trans SA', company_name: 'Trans SA' },
    calculation_method: 'PER_LITRE',
    base_amount: '2925000.00',
    unit_price_per_litre: '65.0000',
    deduction_amount: '0.00',
    advance_applied: null,
    net_amount: '2925000.00',
    status: 'PLANNED',
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

describe('TripDetail expenses section', () => {
  it('does not delete a commission when confirmation is declined', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    transportPaymentsToReturn = [makeTransportPayment({ can_modify: true })]
    const wrapper = await mountAt()
    confirmDialogMock.mockResolvedValueOnce(false)
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Supprimer')!
      .trigger('click')
    expect(removeTransportPayment).not.toHaveBeenCalled()
  })

  it('hides commission actions when the API marks it settled or the user has no write permissions', async () => {
    setUser({ operations: ['view'], finance: ['view', 'edit', 'cancel'] })
    transportPaymentsToReturn = [makeTransportPayment({ can_modify: false })]
    const settled = await mountAt()
    expect(
      settled.findAll('button').some((b) => ['Modifier', 'Supprimer'].includes(b.text())),
    ).toBe(false)
    settled.unmount()
    setUser({ operations: ['view'], finance: ['view'] })
    transportPaymentsToReturn = [makeTransportPayment({ can_modify: true })]
    const readonly = await mountAt()
    expect(
      readonly.findAll('button').some((b) => ['Modifier', 'Supprimer'].includes(b.text())),
    ).toBe(false)
  })

  it('shows deletion errors and keeps the commission visible', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    transportPaymentsToReturn = [makeTransportPayment({ can_modify: true })]
    removeTransportPayment.mockRejectedValueOnce({
      response: { data: { detail: 'Commission déjà réglée' } },
    })
    const wrapper = await mountAt()
    confirmDialogMock.mockResolvedValueOnce(true)
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Supprimer')!
      .trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Commission déjà réglée')
    expect(wrapper.text()).toContain('Commission transporteur')
  })
  it('deletes an unsettled commission after confirmation and refreshes the fees', async () => {
    setUser({ operations: ['view'], finance: ['view', 'edit', 'cancel'] })
    transportPaymentsToReturn = [makeTransportPayment({ can_modify: true })]
    const wrapper = await mountAt()
    confirmDialogMock.mockResolvedValueOnce(true)
    const before = transportPaymentList.mock.calls.length
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Supprimer')!
      .trigger('click')
    await flushPromises()
    expect(removeTransportPayment).toHaveBeenCalledWith(8)
    expect(transportPaymentList.mock.calls.length).toBeGreaterThan(before)
  })

  it('opens the existing commission with its current rate for editing', async () => {
    setUser({ operations: ['view'], finance: ['view', 'edit'] })
    transportPaymentsToReturn = [makeTransportPayment({ can_modify: true })]
    const wrapper = await mountAt()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Modifier')!
      .trigger('click')
    expect((wrapper.find('#unit_price_per_litre').element as HTMLInputElement).value).toBe(
      '65.0000',
    )
    expect(wrapper.text()).toContain('Modifier la commission transporteur')
  })

  // Bug fix (2026-09-17): once a commission is settled, can_modify flips to
  // false and Modifier/Supprimer disappear - there was no "Annuler" action
  // to replace them, unlike every other trip fee (Expense's own "Annuler").
  it('shows an Annuler action instead of Modifier/Supprimer once the commission is settled', async () => {
    setUser({ operations: ['view'], finance: ['view', 'edit', 'cancel'] })
    transportPaymentsToReturn = [makeTransportPayment({ status: 'PAID', can_modify: false })]
    const wrapper = await mountAt()
    const buttons = wrapper.findAll('button').map((b) => b.text())
    expect(buttons).not.toContain('Modifier')
    expect(buttons).not.toContain('Supprimer')
    expect(buttons).toContain('Annuler')
  })

  it('does not cancel a settled commission when confirmation is declined', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    transportPaymentsToReturn = [makeTransportPayment({ status: 'PAID', can_modify: false })]
    const wrapper = await mountAt()
    confirmDialogMock.mockResolvedValueOnce(false)
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Annuler')!
      .trigger('click')
    expect(cancelTransportPayment).not.toHaveBeenCalled()
  })

  it('cancels a settled commission after confirmation and refreshes the fees', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    transportPaymentsToReturn = [makeTransportPayment({ status: 'PAID', can_modify: false })]
    const wrapper = await mountAt()
    confirmDialogMock.mockResolvedValueOnce(true)
    const before = transportPaymentList.mock.calls.length
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Annuler')!
      .trigger('click')
    await flushPromises()
    expect(cancelTransportPayment).toHaveBeenCalledWith(8)
    expect(transportPaymentList.mock.calls.length).toBeGreaterThan(before)
  })

  it('shows cancellation errors and keeps the commission visible', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    transportPaymentsToReturn = [makeTransportPayment({ status: 'PAID', can_modify: false })]
    cancelTransportPayment.mockRejectedValueOnce({
      response: { data: { detail: 'Commission deja annulee' } },
    })
    const wrapper = await mountAt()
    confirmDialogMock.mockResolvedValueOnce(true)
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Annuler')!
      .trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Commission deja annulee')
    expect(wrapper.text()).toContain('Commission transporteur')
  })

  it('never shows an Annuler action for an already cancelled commission', async () => {
    setUser({ operations: ['view'], finance: ['view', 'edit', 'cancel'] })
    transportPaymentsToReturn = [makeTransportPayment({ status: 'CANCELLED', can_modify: false })]
    const wrapper = await mountAt()
    expect(wrapper.findAll('button').find((b) => b.text() === 'Annuler')).toBeUndefined()
  })

  // Part 2 of the commission-actions bug fix (2026-09-17): a settled
  // commission also gets a "Corriger" action next to "Annuler", so its
  // rate/amount can be fixed in place instead of a full cancel+recreate.
  it('shows a Corriger action next to Annuler once the commission is settled', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    transportPaymentsToReturn = [makeTransportPayment({ status: 'PAID', can_modify: false })]
    const wrapper = await mountAt()
    const buttons = wrapper.findAll('button').map((b) => b.text())
    expect(buttons).toContain('Corriger')
    expect(buttons).toContain('Annuler')
  })

  it('corrects a settled commission and refreshes the fees', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    transportPaymentsToReturn = [
      makeTransportPayment({
        id: 8,
        status: 'PAID',
        can_modify: false,
        calculation_method: 'PER_LITRE',
        unit_price_per_litre: '65.0000',
        base_amount: '2925000',
      }),
    ]
    const wrapper = await mountAt()
    const before = transportPaymentList.mock.calls.length

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Corriger')!
      .trigger('click')
    expect(wrapper.text()).toContain('Corriger la commission transporteur')
    await wrapper.find('#unit_price_per_litre').setValue('60')
    await wrapper.find('#correction_reason').setValue('Taux errone, le bon taux est 60 F/L')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(correctTransportPayment).toHaveBeenCalledWith(8, {
      unit_price_per_litre: '60',
      reason: 'Taux errone, le bon taux est 60 F/L',
    })
    expect(transportPaymentList.mock.calls.length).toBeGreaterThan(before)
  })

  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    tripResourceGet.mockResolvedValue(tripToReturn)
    fetchTripHistory.mockResolvedValue([])
    expensesToReturn = []
    transportPaymentsToReturn = []
    marginToReturn = { available: false }
    allowedStatusesToReturn = ['IN_TRANSIT', 'BLOCKED', 'CANCELLED']
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
    expect(wrapper.text()).toContain('90 000 XOF')
    expect(wrapper.text()).not.toContain('150 000 XOF')
  })

  // Phase 5 (docs/superpowers/specs/2026-09-02-business-corrections-6-
  // phases-design.md): POST /api/expenses/{id}/cancel/ - only for PAID/
  // PARTIALLY_PAID fees, and only for users with the "cancel" tier.
  it('shows a cancel button for a paid trip fee when the user has cancel permission', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    expensesToReturn = [makeExpense({ status: 'PAID' })]

    const wrapper = await mountAt()

    expect(wrapper.findAll('button').find((b) => b.text() === 'Annuler')).toBeDefined()
  })

  it('hides the cancel button without cancel permission', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    expensesToReturn = [makeExpense({ status: 'PAID' })]

    const wrapper = await mountAt()

    expect(wrapper.findAll('button').find((b) => b.text() === 'Annuler')).toBeUndefined()
  })

  it('hides the cancel button for an unpaid fee even with cancel permission', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    expensesToReturn = [makeExpense({ status: 'UNPAID' })]

    const wrapper = await mountAt()

    expect(wrapper.findAll('button').find((b) => b.text() === 'Annuler')).toBeUndefined()
  })

  // Bug fix (2026-09-03 recette manuelle): an UNPAID fee can now be
  // corrected (edit, overwrite in place) or removed outright, instead of
  // only being cancellable once paid.
  it('shows Modifier/Supprimer for an unpaid fee, not for a paid one', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    expensesToReturn = [makeExpense({ id: 6, status: 'UNPAID' })]

    const wrapper = await mountAt()

    expect(wrapper.findAll('button').find((b) => b.text() === 'Modifier')).toBeDefined()
    expect(wrapper.findAll('button').find((b) => b.text() === 'Supprimer')).toBeDefined()

    expensesToReturn = [makeExpense({ id: 6, status: 'PAID' })]
    const paidWrapper = await mountAt()
    expect(paidWrapper.findAll('button').find((b) => b.text() === 'Modifier')).toBeUndefined()
    expect(paidWrapper.findAll('button').find((b) => b.text() === 'Supprimer')).toBeUndefined()
  })

  it('opens the edit form pre-filled when Modifier is clicked, and PATCHes on save', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    expensesToReturn = [makeExpense({ id: 7, status: 'UNPAID', amount: '90000.00' })]

    const wrapper = await mountAt()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Modifier')!
      .trigger('click')
    await flushPromises()

    const amountInput = wrapper.find('#amount').element as HTMLInputElement
    expect(amountInput.value).toBe('90000.00')

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(updateExpense).toHaveBeenCalledWith(7, expect.objectContaining({ amount: '90000.00' }))
    expect(createExpense).not.toHaveBeenCalled()
  })

  it('deletes an unpaid fee after confirmation and reloads the list', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    expensesToReturn = [makeExpense({ id: 8, status: 'UNPAID' })]
    confirmDialogMock.mockResolvedValueOnce(true)

    const wrapper = await mountAt()
    expect(expenseList).toHaveBeenCalledTimes(1)

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Supprimer')!
      .trigger('click')
    await flushPromises()

    expect(removeExpense).toHaveBeenCalledWith(8)
    expect(expenseList).toHaveBeenCalledTimes(2)
  })

  it('does not delete an unpaid fee when the confirmation is declined', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    expensesToReturn = [makeExpense({ id: 9, status: 'UNPAID' })]
    confirmDialogMock.mockResolvedValueOnce(false)

    const wrapper = await mountAt()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Supprimer')!
      .trigger('click')
    await flushPromises()

    expect(removeExpense).not.toHaveBeenCalled()
  })

  it('cancels a paid trip fee and reloads the expenses list', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    expensesToReturn = [makeExpense({ id: 5, status: 'PARTIALLY_PAID' })]

    const wrapper = await mountAt()
    expect(expenseList).toHaveBeenCalledTimes(1)

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Annuler')!
      .trigger('click')
    await flushPromises()

    expect(cancelExpense).toHaveBeenCalledWith(5)
    expect(expenseList).toHaveBeenCalledTimes(2)
  })

  it('shows a cancelled fee as cancelled, with no cancel button', async () => {
    setUser({ operations: ['view'], finance: ['view', 'cancel'] })
    expensesToReturn = [makeExpense({ status: 'CANCELLED' })]

    const wrapper = await mountAt()

    expect(wrapper.text()).toContain('Frais annulé')
    expect(wrapper.findAll('button').find((b) => b.text() === 'Annuler')).toBeUndefined()
  })

  // Bug fix (2026-09-03 recette manuelle): a TransportPayment cancelled
  // alongside its trip (TripCancellationService, backend) used to render
  // as a plain, active-looking line - no different from a real debt.
  it('shows a cancelled transport payment as cancelled, struck through', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    transportPaymentsToReturn = [makeTransportPayment({ status: 'CANCELLED' })]

    const wrapper = await mountAt()

    expect(wrapper.text()).toContain('Paiement transport annulé')
  })

  it('shows transporter commission together with trip expenses', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    transportPaymentsToReturn = [makeTransportPayment()]

    const wrapper = await mountAt()

    expect(transportPaymentList).toHaveBeenCalledWith({ trip: 9 })
    expect(wrapper.text()).toContain('Commission transporteur')
    expect(wrapper.text()).toContain('65')
    expect(wrapper.text()).toContain('2 925 000 XOF')
  })

  const COMMISSION_VALUE = '__transport_commission__'
  const openAddExpense = async (wrapper: Awaited<ReturnType<typeof mountAt>>) => {
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Ajouter un frais'))!
      .trigger('click')
    await flushPromises()
  }

  it('no longer shows a separate "Add transport fee" button', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    const wrapper = await mountAt()
    expect(wrapper.text()).not.toContain('Ajouter des frais de transport')
  })

  it('offers "Commission transporteur" in the add-expense category list and switches to the commission form', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    const wrapper = await mountAt()
    await openAddExpense(wrapper)

    const option = wrapper.find(`#category option[value="${COMMISSION_VALUE}"]`)
    expect(option.exists()).toBe(true)
    expect(option.text()).toBe('Commission transporteur')

    await wrapper.find('#category').setValue(COMMISSION_VALUE)
    await flushPromises()

    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(true)
    expect(wrapper.find('#category').exists()).toBe(false)
  })

  it('hides the commission option once a payment exists for the trip', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    transportPaymentsToReturn = [makeTransportPayment()]
    const wrapper = await mountAt()
    await openAddExpense(wrapper)

    expect(wrapper.find(`#category option[value="${COMMISSION_VALUE}"]`).exists()).toBe(false)
  })

  it('hides the commission option for an internal (company fleet) transporter', async () => {
    setUser({ operations: ['view'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(
      makeTrip({ transporter_detail: { id: 2, name: 'Flotte propre', is_internal: true } }),
    )
    const wrapper = await mountAt()
    await openAddExpense(wrapper)

    expect(wrapper.find(`#category option[value="${COMMISSION_VALUE}"]`).exists()).toBe(false)
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
    marginToReturn = makeMargin({
      revenue: '29152500.00',
      fuel_purchase_cost: '27000000.00',
      transport_cost: '500000.00',
      expenses_by_category: { customs: '90000.00' },
      total_expenses: '90000.00',
      real_total_cost: '27590000.00',
      margin: '1562500.00',
      unit_cost: '611.11',
      unit_profit: '38.89',
    })

    const wrapper = await mountAt()

    // Amounts are wrapped in bidi isolate marks (LRI/PDI) so they can't be
    // reordered in RTL locales; strip them before matching adjacent text
    // (the leading "-" here is concatenated outside the formatter's isolate).
    const text = wrapper.text().replace(/[⁦⁩]/g, '')
    expect(text).toContain('29 152 500 XOF')
    expect(text).toContain('-27 000 000 XOF')
    expect(text).toContain('-500 000 XOF')
    expect(text).toContain('-90 000 XOF')
    expect(text).toContain('1 562 500 XOF')
  })

  // UI recette bug (2026-09-04): the backend already computed
  // company_absorbed_loss_amount/_quantity correctly (a post-delivery loss
  // within the 100 L tolerance, absorbed by the company, already baked
  // into margin) but the frontend never rendered a line for it - fixed by
  // exposing the row only when the amount is > 0, client's own example.
  // Task 12 (Version A): the row stays visible but reads as greyed information
  // (it is already reflected in the reduced revenue), not as a red deduction.
  it('shows a greyed "perte supportee par l\'entreprise" information row when a loss within tolerance is absorbed', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    marginToReturn = makeMargin({
      company_absorbed_loss_quantity: '100.00',
      company_absorbed_loss_amount: '90000.00',
      margin: '4730000.00',
    })

    const wrapper = await mountAt()

    const row = wrapper.find('[data-test="company-absorbed-loss-row"]')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain("Perte supportée par l'entreprise")
    // no critical (red) styling any more - it is information, not a deduction
    expect(row.find('.text-critique').exists()).toBe(false)
    const text = row.text().replace(/[⁦⁩]/g, '')
    expect(text).toContain('information')
    // amount shown without a leading "-" (not a deduction)
    expect(text).toContain('90 000 XOF')
    expect(text).not.toContain('-90 000 XOF')
    // detail: 100 L x 900,0000 XOF/L (900 = 90000 / 100, derived, never sent by the backend)
    expect(text).toContain('100 L')
    expect(text).toContain('900,0000 XOF/L')
  })

  it('hides the "perte supportee par l\'entreprise" row when there is no absorbed loss', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    marginToReturn = makeMargin({
      company_absorbed_loss_quantity: '0.00',
      company_absorbed_loss_amount: '0.00',
    })

    const wrapper = await mountAt()

    expect(wrapper.find('[data-test="company-absorbed-loss-row"]').exists()).toBe(false)
  })

  it('shows only the company-absorbed part above the threshold, keeping the transporter part separate', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    // 150 L loss: 100 L tolerated (company-absorbed), 50 L chargeable
    // (transporter) - the two parts must never overlap.
    marginToReturn = makeMargin({
      transporter_loss_quantity: '50.00',
      transporter_loss_indemnity: '32500.00',
      company_absorbed_loss_quantity: '100.00',
      company_absorbed_loss_amount: '65000.00',
    })

    const wrapper = await mountAt()

    const row = wrapper.find('[data-test="company-absorbed-loss-row"]')
    expect(row.exists()).toBe(true)
    const text = wrapper.text().replace(/[⁦⁩]/g, '')
    // Company-absorbed: 100 L, 65 000 XOF shown as information (no leading "-").
    expect(row.text().replace(/[⁦⁩]/g, '')).toContain('100 L')
    expect(row.text().replace(/[⁦⁩]/g, '')).toContain('65 000 XOF')
    expect(row.text().replace(/[⁦⁩]/g, '')).not.toContain('-65 000 XOF')
    expect(row.find('.text-critique').exists()).toBe(false)
    // Transporter part stays displayed separately, unaffected.
    expect(text).toContain('50 L')
    expect(text).toContain('32 500 XOF')
  })

  it('highlights a negative margin', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    marginToReturn = makeMargin({
      quantity_loaded: '1.00',
      quantity_invoiced: '1.00',
      revenue: '1000.00',
      fuel_purchase_cost: '2000.00',
      transport_cost: '0.00',
      expenses_by_category: {},
      total_expenses: '0.00',
      real_total_cost: '2000.00',
      margin: '-1000.00',
      unit_cost: '2000.00',
      unit_profit: '-1500.00',
    })

    const wrapper = await mountAt()

    const marginValue = wrapper.findAll('dd').find((dd) => dd.text().includes('-1 000'))
    expect(marginValue?.find('span').classes()).toContain('text-critique')
  })

  it('shows "Stock de l\'entreprise" for a COMPANY_STOCK trip instead of a generic direct-sale label', async () => {
    setUser({ operations: ['view'], finance: ['view'] })

    const wrapper = await mountAt()

    expect(wrapper.text()).toContain("Stock de l'entreprise")
    expect(wrapper.text()).not.toContain('Vente directe')
  })

  it('shows "Attribuer un client" for a COMPANY_STOCK trip with operations edit and no sale yet', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    marginToReturn = { available: false }
    tripResourceGet.mockResolvedValueOnce(makeTrip({ status: 'CUSTOMS' }))

    const wrapper = await mountAt()

    expect(wrapper.findAll('button').find((b) => b.text() === 'Attribuer un client')).toBeDefined()
  })

  it('hides "Attribuer un client" without operations edit permission', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    marginToReturn = { available: false }

    const wrapper = await mountAt()

    expect(
      wrapper.findAll('button').find((b) => b.text() === 'Attribuer un client'),
    ).toBeUndefined()
  })

  it('hides "Attribuer un client" once the trip already has a Sale (mirrors the backend reject-after-sale rule)', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    marginToReturn = makeMargin({
      quantity_loaded: '1.00',
      quantity_invoiced: '1.00',
      revenue: '1000.00',
      fuel_purchase_cost: '500.00',
      transport_cost: '0.00',
      expenses_by_category: {},
      total_expenses: '0.00',
      real_total_cost: '500.00',
      margin: '500.00',
      unit_cost: '500.00',
      unit_profit: '11.11',
    })

    const wrapper = await mountAt()

    expect(
      wrapper.findAll('button').find((b) => b.text() === 'Attribuer un client'),
    ).toBeUndefined()
  })

  it('opens the assign-customer overlay when "Attribuer un client" is clicked', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    marginToReturn = { available: false }
    tripResourceGet.mockResolvedValueOnce(makeTrip({ status: 'CUSTOMS' }))

    const wrapper = await mountAt()
    const button = wrapper.findAll('button').find((b) => b.text() === 'Attribuer un client')
    await button!.trigger('click')

    expect(wrapper.text()).toContain('TRIP-009')
  })

  it('hides assign customer before customs even when there is no sale yet', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    marginToReturn = { available: false }
    tripResourceGet.mockResolvedValueOnce(makeTrip({ status: 'IN_TRANSIT' }))

    const wrapper = await mountAt()

    expect(
      wrapper.findAll('button').find((b) => b.text() === 'Attribuer un client'),
    ).toBeUndefined()
  })

  it('shows only backend-allowed next statuses', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet.mockResolvedValueOnce(makeTrip({ status: 'CUSTOMS', client: null }))
    allowedStatusesToReturn = ['ARRIVED_AT_COMPANY_STOCK', 'BLOCKED']

    const wrapper = await mountAt()

    const optionText = wrapper.find('#next_status').text()
    expect(fetchAllowedTripStatuses).toHaveBeenCalledWith(9)
    expect(optionText).toContain('Arrivé au stock entreprise')
    expect(optionText).not.toContain('En route vers le client')
    expect(optionText).not.toContain('Arrivé chez le client')
    expect(optionText).not.toContain('Contrôle de quantité')
  })

  it('never offers Livré/Terminé in the status bar and still refreshes allowed statuses after delivery', async () => {
    // 2026-09-07 recette: DELIVERED and COMPLETED are form-only - the
    // backend allowed-statuses endpoint strips them, so the status bar must
    // never list them however the trip is sitting. The delivery form (not
    // the bar) drives the DELIVERED transition; this only checks the bar
    // stays clean and that onDeliveryConfirmed still re-fetches the list.
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet
      .mockResolvedValueOnce(makeTrip({ status: 'QUANTITY_CONTROL', client: 10 }))
      .mockResolvedValueOnce(makeTrip({ status: 'DELIVERED', client: 10 }))
    allowedStatusesToReturn = ['CANCELLED', 'BLOCKED']
    postDeliveryControl.mockImplementationOnce(async (_tripId, payload) => {
      allowedStatusesToReturn = ['BLOCKED']
      return {
        id: 1,
        trip: 9,
        loaded_quantity: '45000.00',
        received_quantity: '45000.00',
        loss_quantity: '0.00',
        chargeable_loss_quantity: '0.00',
        tolerance_quantity: '100.00',
        control_date: payload.control_date,
        controller: 1,
        controller_detail: null,
        method: payload.method,
        document: null,
        notes: '',
        anomaly_confirmed_by: null,
        anomaly_confirmed_by_detail: null,
        anomaly_confirmed_at: null,
        created_at: '',
        updated_at: '',
      }
    })

    const wrapper = await mountAt()
    expect(wrapper.find('#next_status').text()).not.toContain('Livré')

    await wrapper.find('#control_date').setValue('2026-08-18')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    const optionText = wrapper.find('#next_status').text()
    expect(fetchAllowedTripStatuses).toHaveBeenCalledTimes(2)
    expect(optionText).not.toContain('Terminé')
    expect(optionText).not.toContain('Livré')
  })

  it('shows the delivery confirmation form straight from ARRIVED_AT_CLIENT (simplified flow)', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet.mockResolvedValueOnce(makeTrip({ status: 'ARRIVED_AT_CLIENT', client: 10 }))
    // The backend strips the form-only DELIVERED from allowed-statuses here.
    allowedStatusesToReturn = ['CANCELLED', 'BLOCKED']

    const wrapper = await mountAt()

    expect(wrapper.find('#control_date').exists()).toBe(true)
    expect(wrapper.find('#next_status').text()).not.toContain('Livré')
    expect(
      wrapper
        .findAll('button')
        .find((b) => b.text() === 'Enregistrer la quantité reçue par le client'),
    ).toBeUndefined()
  })

  it('shows the client-verification action once the trip is DELIVERED, and records a verification', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet
      .mockResolvedValueOnce(makeTrip({ status: 'DELIVERED', client: 10 }))
      .mockResolvedValueOnce(makeTrip({ status: 'DELIVERED', client: 10 }))
    allowedStatusesToReturn = ['COMPLETED']

    const wrapper = await mountAt()
    expect(wrapper.find('#control_date').exists()).toBe(false)
    const button = wrapper
      .findAll('button')
      .find((b) => b.text() === 'Enregistrer la quantité reçue par le client')
    expect(button).toBeTruthy()

    await button!.trigger('click')
    await wrapper.find('[data-test="received-quantity"]').setValue('44850')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(postClientVerification).toHaveBeenCalledWith(
      9,
      expect.objectContaining({ verified_at: expect.any(String) }),
    )
  })

  it('reflects the trip closing itself once the client-verification reload comes back COMPLETED', async () => {
    // Client request (2026-09-06): DeliveryService.record_client_verification
    // now closes the trip on the backend in the same call - the reload this
    // component already does right after submission (onClientVerified ->
    // load()) is enough to show that on its own, no new frontend code
    // needed. Locking in that the existing reactive reload actually
    // surfaces it: once the second load() resolves with status COMPLETED,
    // the badge updates and the action button (gated on trip.status too)
    // disappears - not just on the already-covered clientAlreadyVerified path.
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet
      .mockResolvedValueOnce(makeTrip({ status: 'DELIVERED', client: 10 }))
      .mockResolvedValueOnce(makeTrip({ status: 'COMPLETED', client: 10 }))
    allowedStatusesToReturn = ['COMPLETED']

    const wrapper = await mountAt()
    const button = wrapper
      .findAll('button')
      .find((b) => b.text() === 'Enregistrer la quantité reçue par le client')
    await button!.trigger('click')
    await wrapper.find('[data-test="received-quantity"]').setValue('44850')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Terminé')
  })

  it('hides the client-verification action and shows a read-only block once a verification is already recorded', async () => {
    // Bug fix (recette corrections 2026-09-05): the button used to stay
    // visible after a client verification was already recorded, letting a
    // loss be declared a second time on the same trip.
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet.mockResolvedValueOnce(makeTrip({ status: 'DELIVERED', client: 10 }))
    allowedStatusesToReturn = ['COMPLETED']
    fetchReport.mockResolvedValueOnce({
      rows: [
        {
          trip_reference: 'TRIP-009',
          control_date: '2026-08-18',
          loaded_quantity: '45000.00',
          received_quantity: '44850.00',
          loss_quantity: '150.00',
          tolerance_quantity: '100.00',
          chargeable_loss_quantity: '50.00',
          verified_at: '2026-08-19',
          notes: 'Ecart signale par le client',
        },
      ],
    })

    const wrapper = await mountAt()

    expect(
      wrapper
        .findAll('button')
        .find((b) => b.text() === 'Enregistrer la quantité reçue par le client'),
    ).toBeUndefined()
    const readOnlyBlock = wrapper.find('[data-test="client-verification-recorded"]')
    expect(readOnlyBlock.exists()).toBe(true)
    expect(readOnlyBlock.text()).toContain('Vérification client enregistrée')
    expect(readOnlyBlock.text()).toContain('2026-08-19')
    expect(readOnlyBlock.text()).toContain('Ecart signale par le client')
  })

  it('only shows the verification-correction action with the "validate" permission tier', async () => {
    // Feedback (2026-09-10): the correction is audited and gated behind
    // "validate" (backend/apps/accounts/permissions.py ACTION_MAP
    // "correct_client_verification"), a stricter tier than the routine
    // "edit" used by the first verification.
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet.mockResolvedValueOnce(makeTrip({ status: 'DELIVERED', client: 10 }))
    allowedStatusesToReturn = ['COMPLETED']
    fetchReport.mockResolvedValueOnce({
      rows: [
        {
          trip_reference: 'TRIP-009',
          control_date: '2026-08-18',
          loaded_quantity: '45000.00',
          received_quantity: '100.00',
          loss_quantity: '44900.00',
          tolerance_quantity: '100.00',
          chargeable_loss_quantity: '44800.00',
          verified_at: '2026-08-19',
          notes: '',
        },
      ],
    })

    const wrapper = await mountAt()

    expect(
      wrapper.findAll('button').find((b) => b.text() === 'Corriger la vérification client'),
    ).toBeUndefined()
  })

  it('submits a client-verification correction and shows the correction history', async () => {
    // Feedback (2026-09-10): the operator typed the loss (100 L) instead of
    // the received quantity - DeliveryService.correct_client_verification()
    // is the audited fix, surfaced here via ClientVerificationCorrectionForm.
    setUser({ operations: ['view', 'edit', 'validate'], finance: ['view'] })
    tripResourceGet
      .mockResolvedValueOnce(makeTrip({ status: 'COMPLETED', client: 10 }))
      .mockResolvedValueOnce(
        makeTrip({
          status: 'COMPLETED',
          client: 10,
          delivery_control_detail: {
            id: 1,
            trip: 9,
            loaded_quantity: '45000.00',
            received_quantity: '44900.00',
            loss_quantity: '100.00',
            chargeable_loss_quantity: '0.00',
            tolerance_quantity: '100.00',
            control_date: '2026-08-18',
            controller: 1,
            controller_detail: null,
            method: 'MANUAL_GAUGE',
            document: null,
            notes: '',
            anomaly_confirmed_by: null,
            anomaly_confirmed_by_detail: null,
            anomaly_confirmed_at: null,
            verified_at: '2026-08-19',
            verification_corrections: [
              {
                id: 1,
                previous_received_quantity: '100.00',
                new_received_quantity: '44900.00',
                corrected_by: 1,
                corrected_by_detail: { id: 1, full_name: 'Admin', email: 'admin@example.com' },
                corrected_at: '2026-08-20T10:00:00Z',
                reason: "L'operateur a saisi la perte au lieu de la quantite recue",
              },
            ],
            created_at: '',
            updated_at: '',
          },
        }),
      )
    allowedStatusesToReturn = []
    const lossReportRow = {
      trip_reference: 'TRIP-009',
      control_date: '2026-08-18',
      loaded_quantity: '45000.00',
      received_quantity: '100.00',
      loss_quantity: '44900.00',
      tolerance_quantity: '100.00',
      chargeable_loss_quantity: '44800.00',
      verified_at: '2026-08-19',
      notes: '',
    }
    fetchReport
      .mockResolvedValueOnce({ rows: [lossReportRow] })
      .mockResolvedValueOnce({ rows: [lossReportRow] })

    const wrapper = await mountAt()

    const openButton = wrapper
      .findAll('button')
      .find((b) => b.text() === 'Corriger la vérification client')
    expect(openButton).toBeTruthy()
    await openButton!.trigger('click')

    await wrapper.find('[data-test="correction-received-quantity"]').setValue('44900')
    await wrapper
      .find('[data-test="correction-reason"]')
      .setValue("L'operateur a saisi la perte au lieu de la quantite recue")
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(postClientVerificationCorrection).toHaveBeenCalledWith(
      9,
      expect.objectContaining({
        reason: "L'operateur a saisi la perte au lieu de la quantite recue",
      }),
    )
    const history = wrapper.find('[data-test="verification-correction-history"]')
    expect(history.exists()).toBe(true)
    expect(history.text()).toContain('100')
    expect(history.text()).toContain('44 900')
  })

  it('also shows the client-verification action once the trip is COMPLETED, but never for CANCELLED', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet.mockResolvedValueOnce(makeTrip({ status: 'COMPLETED', client: 10 }))
    allowedStatusesToReturn = []

    const wrapper = await mountAt()
    expect(
      wrapper
        .findAll('button')
        .find((b) => b.text() === 'Enregistrer la quantité reçue par le client'),
    ).toBeTruthy()
  })

  it('never shows the client-verification action for a CANCELLED trip', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet.mockResolvedValueOnce(makeTrip({ status: 'CANCELLED', client: 10 }))
    allowedStatusesToReturn = []

    const wrapper = await mountAt()
    expect(
      wrapper
        .findAll('button')
        .find((b) => b.text() === 'Enregistrer la quantité reçue par le client'),
    ).toBeUndefined()
  })

  it('shows the source cession proof in an internal preview modal', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    tripResourceGet.mockResolvedValueOnce(
      makeTrip({
        cession_letter_detail: {
          ...makeTrip().cession_letter_detail!,
          documents: [
            {
              id: 14,
              file: '/media/documents/cession-trip.webp',
              document_type: 'cession_proof',
              reference: '',
              uploaded_by: 1,
              uploaded_by_email: 'admin@example.com',
              created_at: '',
            },
          ],
        },
      }),
    )

    const wrapper = await mountAt()

    const proofButton = wrapper
      .findAll('button')
      .find((button) => button.text() === 'Voir justificatif')
    expect(proofButton).toBeTruthy()
    await proofButton!.trigger('click')
    await flushPromises()

    expect(wrapper.find('img[src="/media/documents/cession-trip.webp"]').exists()).toBe(true)
  })

  it('opens the transporter commission popup after ASSIGNED -> SENT_FOR_LOADING', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'ASSIGNED' }))
    allowedStatusesToReturn = ['SENT_FOR_LOADING']

    const wrapper = await mountAt()
    await wrapper.find('#next_status').setValue('SENT_FOR_LOADING')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Appliquer')!
      .trigger('click')
    await flushPromises()

    expect(postTripStatus).toHaveBeenCalledWith(9, 'SENT_FOR_LOADING', '')
    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(true)
    expect(wrapper.text()).toContain('Commission du transporteur')
  })

  it('does not reopen the transporter commission popup when a payment already exists for the trip', async () => {
    // Bug fix (found by chance, client feedback 2026-09-10): nothing
    // stopped a second TransportPayment from being created for a trip
    // that already has one - this popup was one of the two ways it
    // happened (the always-visible "Ajouter des frais de transport"
    // button was the other, covered below).
    setUser({ operations: ['view', 'edit'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'ASSIGNED' }))
    allowedStatusesToReturn = ['SENT_FOR_LOADING']
    transportPaymentsToReturn = [makeTransportPayment()]

    const wrapper = await mountAt()
    await wrapper.find('#next_status').setValue('SENT_FOR_LOADING')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Appliquer')!
      .trigger('click')
    await flushPromises()

    expect(postTripStatus).toHaveBeenCalledWith(9, 'SENT_FOR_LOADING', '')
    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(false)
  })

  it('opens a prefilled per-litre loading expense popup after SENT_FOR_LOADING -> LOADING', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'SENT_FOR_LOADING' }))
    allowedStatusesToReturn = ['LOADING']

    const wrapper = await mountAt()
    await wrapper.find('#next_status').setValue('LOADING')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Appliquer')!
      .trigger('click')
    await flushPromises()

    expect((wrapper.find('#category').element as HTMLSelectElement).value).toBe('loading')
    expect((wrapper.find('#calculation_method').element as HTMLSelectElement).value).toBe(
      'PER_LITRE',
    )
    expect(wrapper.text()).toContain('TRIP-009')
  })

  it('opens a separate road transit expense popup after LOADED -> ROAD_TRANSIT', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'LOADED' }))
    allowedStatusesToReturn = ['ROAD_TRANSIT']

    const wrapper = await mountAt()
    await wrapper.find('#next_status').setValue('ROAD_TRANSIT')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Appliquer')!
      .trigger('click')
    await flushPromises()

    expect(postTripStatus).toHaveBeenCalledWith(9, 'ROAD_TRANSIT', '')
    expect((wrapper.find('#category').element as HTMLSelectElement).value).toBe('road_transit')
    expect((wrapper.find('#calculation_method').element as HTMLSelectElement).value).toBe(
      'PER_LITRE',
    )
    expect(wrapper.text()).toContain('Transit routière')
  })

  it('opens a transit expense popup after ROAD_TRANSIT -> IN_TRANSIT without using transport', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'ROAD_TRANSIT' }))
    allowedStatusesToReturn = ['IN_TRANSIT']

    const wrapper = await mountAt()
    await wrapper.find('#next_status').setValue('IN_TRANSIT')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Appliquer')!
      .trigger('click')
    await flushPromises()

    expect(postTripStatus).toHaveBeenCalledWith(9, 'IN_TRANSIT', '')
    expect((wrapper.find('#category').element as HTMLSelectElement).value).toBe('transit')
    expect((wrapper.find('#category').element as HTMLSelectElement).value).not.toBe('transport')
    expect(wrapper.text()).toContain('Frais transit')
  })

  async function applyStatus(wrapper: Awaited<ReturnType<typeof mountAt>>, status: string) {
    await wrapper.find('#next_status').setValue(status)
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Appliquer')!
      .trigger('click')
    await flushPromises()
  }
  const buttonNamed = (wrapper: Awaited<ReturnType<typeof mountAt>>, label: string) =>
    wrapper.findAll('button').find((b) => b.text() === label)

  it('chains one fee popup per skipped status, each with a "Passer" button', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'ASSIGNED' }))
    allowedStatusesToReturn = ['LOADING']
    postTripStatus.mockResolvedValueOnce({
      ...makeTrip({ status: 'ROAD_TRANSIT' }),
      traversed_statuses: ['SENT_FOR_LOADING', 'LOADING', 'LOADED', 'ROAD_TRANSIT'],
    })

    const wrapper = await mountAt()
    await applyStatus(wrapper, 'LOADING')

    // 1) transporter commission
    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(true)
    await buttonNamed(wrapper, 'Passer')!.trigger('click')
    await flushPromises()
    // 2) loading fee
    expect((wrapper.find('#category').element as HTMLSelectElement).value).toBe('loading')
    await buttonNamed(wrapper, 'Passer')!.trigger('click')
    await flushPromises()
    // 3) road transit fee (LOADED carries none)
    expect((wrapper.find('#category').element as HTMLSelectElement).value).toBe('road_transit')
    await buttonNamed(wrapper, 'Passer')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('#category').exists()).toBe(false)
    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(false)
  })

  it('"Tout passer" closes the whole fee queue at once', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view', 'create'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'ASSIGNED' }))
    allowedStatusesToReturn = ['LOADING']
    postTripStatus.mockResolvedValueOnce({
      ...makeTrip({ status: 'CUSTOMS' }),
      traversed_statuses: ['SENT_FOR_LOADING', 'LOADING', 'ROAD_TRANSIT', 'CUSTOMS'],
    })

    const wrapper = await mountAt()
    await applyStatus(wrapper, 'LOADING')
    await buttonNamed(wrapper, 'Tout passer')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('#category').exists()).toBe(false)
    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(false)
  })

  it('opens no fee popup and stays usable after a skip without finance create permission', async () => {
    setUser({ operations: ['view', 'edit'], finance: ['view'] })
    tripResourceGet.mockResolvedValue(makeTrip({ status: 'ASSIGNED' }))
    allowedStatusesToReturn = ['LOADING']
    postTripStatus.mockResolvedValueOnce({
      ...makeTrip({ status: 'LOADING' }),
      traversed_statuses: ['SENT_FOR_LOADING', 'LOADING'],
    })

    const wrapper = await mountAt()
    await applyStatus(wrapper, 'LOADING')

    expect(wrapper.find('#category').exists()).toBe(false)
    expect(wrapper.find('#unit_price_per_litre').exists()).toBe(false)
    expect(wrapper.find('#next_status').exists()).toBe(true)
  })

  it('shows road transit as its own line in expenses and margin breakdown', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    expensesToReturn = [
      makeExpense({
        category: 'road_transit',
        amount: '450000.00',
        allocations_detail: [
          {
            id: 2,
            expense: 1,
            content_type: 12,
            content_type_name: 'trip',
            object_id: 9,
            content_object_repr: 'TRIP-009',
            allocated_amount: '450000.00',
            created_at: '',
          },
        ],
      }),
    ]
    marginToReturn = makeMargin({
      expenses_by_category: { road_transit: '450000.00' },
      total_expenses: '450000.00',
      real_total_cost: '27950000.00',
      margin: '1202500.00',
    })

    const wrapper = await mountAt()

    expect(wrapper.text()).toContain('Transit routière')
    expect(wrapper.text().replace(/[⁦⁩]/g, '')).toContain('-450 000 XOF')
  })

  it('shows classic transit as a transit line instead of transport', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    expensesToReturn = [
      makeExpense({
        category: 'transit',
        amount: '90000.00',
        allocations_detail: [
          {
            id: 3,
            expense: 1,
            content_type: 12,
            content_type_name: 'trip',
            object_id: 9,
            content_object_repr: 'TRIP-009',
            allocated_amount: '90000.00',
            created_at: '',
          },
        ],
      }),
    ]
    marginToReturn = makeMargin({
      expenses_by_category: { transit: '90000.00' },
      total_expenses: '90000.00',
      real_total_cost: '27590000.00',
      margin: '1562500.00',
    })

    const wrapper = await mountAt()

    expect(wrapper.text()).toContain('Transit')
    expect(wrapper.text().replace(/[⁦⁩]/g, '')).toContain('-90 000 XOF')
    expect(wrapper.text()).not.toContain('Transport: -90 000')
  })

  it('shows the unit cost and unit profit lines from the margin breakdown', async () => {
    setUser({ operations: ['view'], finance: ['view'] })
    marginToReturn = makeMargin({
      revenue: '29152500.00',
      fuel_purchase_cost: '27000000.00',
      transport_cost: '500000.00',
      expenses_by_category: {},
      total_expenses: '0.00',
      real_total_cost: '27500000.00',
      margin: '1652500.00',
      unit_cost: '611.11',
      unit_profit: '38.89',
    })

    const wrapper = await mountAt()

    const text = wrapper.text()
    expect(text).toContain('611,1100 XOF/L')
    expect(text).toContain('38,8900 XOF/L')
  })
})
