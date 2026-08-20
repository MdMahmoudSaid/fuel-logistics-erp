import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '../DashboardView.vue'
import type { DashboardSummary } from '../types'
import type { Trip } from '@/modules/trips/types'
import type { CustomerPayment } from '@/modules/finance/types'
import type { ReportResponse } from '@/modules/reports/types'

const todayIso = new Date().toISOString().slice(0, 10)

const summary: DashboardSummary = {
  date_from: '2026-08-01',
  date_to: '2026-08-18',
  operations: { trips_count: 5, active_trips_count: 2, delivered_trips_count: 3 },
  fuel: { quantity_loaded: '225000.00', theoretical_stock: '80000.00' },
  sales: { sales_count: 3, revenue: '14580000.00' },
  transport: { settlements_count: 3, transport_cost: '4500000.00' },
  finance: { expenses_total: '600000.00', treasury_balance: '12000000.00' },
  profit: { total_margin: '1957500.00' },
}

const fetchDashboardSummary = vi.fn(async (params: Record<string, string | undefined>) => {
  void params
  return summary
})

vi.mock('../api', () => ({
  fetchDashboardSummary: (params: Record<string, string | undefined>) =>
    fetchDashboardSummary(params),
}))

const fetchReport = vi.fn(async (): Promise<ReportResponse> => ({
  report_type: 'loss-report',
  fields: [],
  rows: [],
}))

vi.mock('@/modules/reports/api', () => ({
  fetchReport: (...args: unknown[]) => fetchReport(...(args as [])),
}))

const trips: Trip[] = [
  {
    id: 1,
    reference: 'TRIP-000042',
    truck: 1,
    truck_detail: {
      id: 1,
      internal_id: 'TRK-01',
      tractor_registration: 'AA-1',
      tanker_registration: 'AA-2',
      capacity_litres: '30000',
      status: 'ON_TRIP',
      owner_transporter: null,
      default_driver: null,
    },
    transporter: 1,
    transporter_detail: { id: 1, name: 'Transporteur 1' },
    driver: null,
    driver_detail: null,
    supplier: 1,
    supplier_detail: { id: 1, name: 'Supplier 1' },
    supplier_order: 1,
    cession_letter: 1,
    product: 1,
    product_detail: { id: 1, name: 'Gasoil', code: 'GO' },
    quantity_loaded: '10000.00',
    client: null,
    client_detail: null,
    customer_order: null,
    loading_date: todayIso,
    bl_reference: 'BL-1',
    status: 'IN_TRANSIT',
    notes: '',
    created_by: null,
    created_by_detail: null,
    created_at: todayIso,
    updated_at: todayIso,
  },
  {
    id: 2,
    reference: 'TRIP-000044',
    truck: 2,
    truck_detail: null,
    transporter: 1,
    transporter_detail: null,
    driver: null,
    driver_detail: null,
    supplier: 1,
    supplier_detail: null,
    supplier_order: 1,
    cession_letter: 1,
    product: 1,
    product_detail: null,
    quantity_loaded: '5000.00',
    client: null,
    client_detail: null,
    customer_order: null,
    loading_date: todayIso,
    bl_reference: 'BL-2',
    status: 'BLOCKED',
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

vi.mock('@/modules/trips/api', () => ({
  tripResource: { list: (...args: unknown[]) => tripList(...(args as [])) },
}))

const payments: CustomerPayment[] = [
  {
    id: 1,
    customer: 1,
    customer_detail: null,
    amount: '500000.00',
    payment_date: todayIso,
    method: 'CASH',
    bank_account: null,
    cash_account: null,
    reference: 'PAY-1',
    is_indirect: false,
    recorded_by: null,
    recorded_by_detail: null,
    allocations_detail: [],
    created_at: todayIso,
    updated_at: todayIso,
  },
]

const paymentList = vi.fn(async () => ({
  count: payments.length,
  next: null,
  previous: null,
  results: payments,
}))

vi.mock('@/modules/finance/api', () => ({
  customerPaymentResource: { list: (...args: unknown[]) => paymentList(...(args as [])) },
}))

function makeRouter() {
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/trips/:id', name: 'trip-detail', component: { template: '<div />' } },
    ],
  })
}

describe('DashboardView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchDashboardSummary.mockImplementation(async () => summary)
    fetchReport.mockImplementation(async () => ({
      report_type: 'loss-report',
      fields: [],
      rows: [
        {
          trip_reference: 'TRIP-000042',
          control_date: todayIso,
          loaded_quantity: '10000.00',
          received_quantity: '9950.00',
          loss_quantity: '50.00',
          tolerance_quantity: '100.00',
          chargeable_loss_quantity: '0.00',
        },
        {
          trip_reference: 'TRIP-000043',
          control_date: todayIso,
          loaded_quantity: '8000.00',
          received_quantity: '7700.00',
          loss_quantity: '300.00',
          tolerance_quantity: '100.00',
          chargeable_loss_quantity: '200.00',
        },
      ],
    }))
    tripList.mockImplementation(async () => ({
      count: trips.length,
      next: null,
      previous: null,
      results: trips,
    }))
    paymentList.mockImplementation(async () => ({
      count: payments.length,
      next: null,
      previous: null,
      results: payments,
    }))
  })

  it('loads the default range on mount and renders all 6 legacy KPI sections', async () => {
    const wrapper = mount(DashboardView, { global: { plugins: [makeRouter()] } })
    await flushPromises()

    expect(fetchDashboardSummary).toHaveBeenCalledWith({ range: 'month' })
    expect(wrapper.text()).toContain('Opérations')
    expect(wrapper.text()).toContain('Carburant')
    expect(wrapper.text()).toContain('Ventes')
    expect(wrapper.text()).toContain('Transport')
    expect(wrapper.text()).toContain('Finance')
    expect(wrapper.text()).toContain('Profit')
    expect(wrapper.text()).toContain('225,000')
    expect(wrapper.text()).toContain('1,957,500')
  })

  it('shows an error message when the summary fails to load', async () => {
    fetchDashboardSummary.mockRejectedValueOnce(new Error('network error'))
    const wrapper = mount(DashboardView, { global: { plugins: [makeRouter()] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Impossible de charger le tableau de bord.')
  })

  it('renders the 4 strategic KPIs, "En route maintenant" and "À traiter" from live-ops data', async () => {
    const wrapper = mount(DashboardView, { global: { plugins: [makeRouter()] } })
    await flushPromises()

    // KPI: volume delivered today = 9950 + 7700 = 17650
    expect(wrapper.text()).toContain('17,650')
    // "En route maintenant": only the IN_TRANSIT trip qualifies (BLOCKED goes to "Urgences")
    expect(wrapper.text()).toContain('En route maintenant (1)')
    expect(wrapper.text()).toContain('TRIP-000042')
    // "À traiter": the row with a chargeable loss
    expect(wrapper.text()).toContain('TRIP-000043')
    // "Urgences": the blocked trip
    expect(wrapper.text()).toContain('TRIP-000044')
  })
})
