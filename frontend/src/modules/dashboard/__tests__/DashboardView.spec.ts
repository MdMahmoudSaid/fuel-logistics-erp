import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '../DashboardView.vue'
import type { DashboardSummary } from '../types'
import type { Trip } from '@/modules/trips/types'
import type { CustomerPayment } from '@/modules/finance/types'
import type { ReportResponse } from '@/modules/reports/types'
import { i18n } from '@/i18n'

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
  debts: {
    total: '3500000.00',
    suppliers: {
      total: '2000000.00',
      rows: [{ supplier: 'Supplier 1', outstanding: '2000000.00' }],
    },
    transporters: {
      total: '1000000.00',
      rows: [{ transporter: 'Transporteur 1', outstanding: '1000000.00' }],
    },
    customs: '400000.00',
    other: '100000.00',
  },
  customer_amounts: {
    total: '750000.00',
    rows: [{ customer: 'Client 1', outstanding: '750000.00' }],
  },
  bank_amounts: {
    total: '5000000.00',
    rows: [{ bank: 'Bank 1', balance: '5000000.00' }],
  },
  cash_amounts: {
    total: '1200000.00',
    rows: [{ cash_account: 'Caisse 1', balance: '1200000.00' }],
  },
  shareholders_summary: {
    current_profit: '900000.00',
    total_withdrawn: '300000.00',
    remaining_undistributed: '600000.00',
    open_loans_total: '50000.00',
  },
  financial_summary: {
    period_revenue: '14580000.00',
    period_collections: '500000.00',
    period_paid_expenses: '600000.00',
    period_accounting_profit: '1957500.00',
    current_treasury_balance: '6200000.00',
  },
  party_balances: {
    customers: {
      balance: '750000.00',
      open_count: 1,
      largest_open: { name: 'Client 1', amount: '750000.00' },
    },
    suppliers: {
      balance: '-2000000.00',
      open_count: 1,
      largest_open: { name: 'Supplier 1', amount: '2000000.00' },
    },
    transporters: {
      balance: '-1000000.00',
      open_count: 1,
      largest_open: { name: 'Transporteur 1', amount: '1000000.00' },
    },
    shareholders: {
      balance: '550000.00',
      remaining_undistributed: '600000.00',
      total_withdrawn: '300000.00',
      open_loans_total: '50000.00',
    },
    customs_and_other: {
      balance: '-500000.00',
      customs: '400000.00',
      other: '100000.00',
    },
  },
  company_stock: {
    total_quantity: '80000.00',
    trips_count: 2,
    by_product: [{ product: 'Gasoil', quantity: '80000.00' }],
    trips: [
      {
        id: 1,
        reference: 'TRIP-000042',
        truck: 'TRK-01',
        supplier: 'Supplier 1',
        transporter: 'Transporteur 1',
        product: 'Gasoil',
        remaining_quantity: '10000.00',
        entry_date: todayIso,
        status: 'ARRIVED_AT_COMPANY_STOCK',
      },
    ],
  },
  action_items: [
    {
      kind: 'company_stock_without_customer',
      label: 'Trajet arrive au stock sans client',
      target: 'trip-detail',
      object_id: 1,
      reference: 'TRIP-000042',
    },
  ],
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
    destination_type: 'COMPANY_STOCK',
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
    destination_type: 'COMPANY_STOCK',
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
    destination: 'CASH',
    note: '',
    recorded_by: null,
    recorded_by_detail: null,
    allocations_detail: [],
    proof_url: null,
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
      { path: '/trips', name: 'trips', component: { template: '<div />' } },
      { path: '/company-stock', name: 'company-stock', component: { template: '<div />' } },
      { path: '/customers', name: 'customers', component: { template: '<div />' } },
      { path: '/suppliers', name: 'suppliers', component: { template: '<div />' } },
      { path: '/transporters', name: 'transporters', component: { template: '<div />' } },
      { path: '/shareholders', name: 'shareholders', component: { template: '<div />' } },
      {
        path: '/treasury/transactions',
        name: 'treasury-transactions',
        component: { template: '<div />' },
      },
      { path: '/profit', name: 'profit', component: { template: '<div />' } },
      {
        path: '/supplier-orders/new',
        name: 'supplier-order-new',
        component: { template: '<div />' },
      },
      {
        path: '/cession-letters/new',
        name: 'cession-letter-new',
        component: { template: '<div />' },
      },
      { path: '/trips/new', name: 'trip-new', component: { template: '<div />' } },
      { path: '/invoices', name: 'invoices', component: { template: '<div />' } },
    ],
  })
}

describe('DashboardView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    i18n.global.locale.value = 'fr'
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
    expect(wrapper.text()).toContain('225 000 L')
    expect(wrapper.text()).toContain('1 957 500 XOF')

    // debts / customer_amounts / bank_amounts sections (point-in-time
    // snapshots, always present alongside the period-filtered sections).
    expect(wrapper.text()).toContain('Total des dettes')
    expect(wrapper.text()).toContain('3 500 000 XOF')
    expect(wrapper.text()).toContain('Montant total des clients')
    expect(wrapper.text()).toContain('Client 1')
    expect(wrapper.text()).toContain('Montant total des banques')
    expect(wrapper.text()).toContain('Bank 1')
    expect(wrapper.text()).toContain('Montant total des caisses')
    expect(wrapper.text()).toContain('Caisse 1')
  })

  it('shows an error message when the summary fails to load', async () => {
    fetchDashboardSummary.mockRejectedValueOnce(new Error('network error'))
    const wrapper = mount(DashboardView, { global: { plugins: [makeRouter()] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Impossible de charger le tableau de bord.')
  })

  it('renders the 4 strategic KPIs and "En route maintenant" from live-ops data', async () => {
    const wrapper = mount(DashboardView, { global: { plugins: [makeRouter()] } })
    await flushPromises()

    // KPI: volume delivered today = 9950 + 7700 = 17650
    expect(wrapper.text()).toContain('17 650 L')
    // "En route maintenant": only the IN_TRANSIT trip qualifies
    expect(wrapper.text()).toContain('En route maintenant (1)')
    expect(wrapper.text()).toContain('TRIP-000042')
  })

  it('renders translated final dashboard cards and routes company stock details to the official page', async () => {
    const router = makeRouter()
    const wrapper = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain("Chiffre d'affaires de la période")
    expect(wrapper.text()).toContain('Encaissements de la période')
    expect(wrapper.text()).toContain('Dépenses payées de la période')
    expect(wrapper.text()).toContain('Bénéfice comptable de la période')
    expect(wrapper.text()).not.toContain(
      'La période filtre les ventes, encaissements, dépenses, volumes et bénéfices.',
    )
    expect(wrapper.findAll('[data-test="financial-kpi-card"]')).toHaveLength(4)
    expect(wrapper.text()).toContain('Trésorerie disponible')
    expect(wrapper.text()).toContain('Banques')
    expect(wrapper.text()).toContain('Caisses')
    expect(wrapper.text()).toContain('Soldes par partie')
    expect(wrapper.text()).toContain("Stock de l'entreprise")
    expect(wrapper.text()).toContain('2 trajet(s) actuellement en stock')

    const partyLinks = wrapper.findAll('[data-test="party-balance-card"]')
    expect(partyLinks).toHaveLength(5)
    expect(partyLinks.map((link) => link.text())).toEqual([
      expect.stringContaining('Clients'),
      expect.stringContaining('Fournisseurs'),
      expect.stringContaining('Transporteurs'),
      expect.stringContaining('Actionnaires / Associés'),
      expect.stringContaining('Douane / Transit / Autres frais'),
    ])
    const partyRouterLinks = wrapper
      .findAllComponents({ name: 'RouterLink' })
      .filter((link) => link.attributes('data-test') === 'party-balance-card')
    expect(partyRouterLinks.map((link) => link.props('to'))).toEqual([
      { name: 'customers' },
      { name: 'suppliers' },
      { name: 'transporters' },
      { name: 'shareholders' },
      { name: 'treasury-transactions' },
    ])

    const stockLink = wrapper
      .findAllComponents({ name: 'RouterLink' })
      .find((link) => link.text() === 'Voir le détail')
    expect(stockLink?.props('to')).toEqual({ name: 'company-stock' })
  })

  it('keeps action work prominent, live trips compact, and period detail collapsed', async () => {
    const wrapper = mount(DashboardView, { global: { plugins: [makeRouter()] } })
    await flushPromises()

    const actionSection = wrapper.find('[data-test="action-items"]')
    expect(actionSection.exists()).toBe(true)
    expect(actionSection.text()).toContain('À traiter')
    expect(actionSection.text()).toContain('TRIP-000042')
    expect(actionSection.classes()).toContain('bg-white')
    expect(actionSection.classes()).toContain('border-ligne')
    expect(actionSection.classes()).not.toContain('bg-orange-tint/40')
    expect(actionSection.find('[data-test="action-count-badge"]').classes()).toContain(
      'bg-orange-tint',
    )

    const actionLink = actionSection.findComponent({ name: 'RouterLink' })
    expect(actionLink.classes()).toContain('bg-sable')
    expect(actionLink.classes()).not.toContain('bg-critique-tint')
    expect(actionLink.classes()).not.toContain('text-critique-texte')

    const normalDebtAmounts = wrapper.findAll('[data-test="party-balance-amount"]')
    expect(normalDebtAmounts.some((amount) => amount.text().includes('-2 000 000 XOF'))).toBe(true)
    expect(
      normalDebtAmounts
        .filter((amount) => amount.text().startsWith('-'))
        .every((amount) => amount.classes().includes('text-texte')),
    ).toBe(true)

    const liveTripsSection = wrapper.find('[data-test="en-route-compact"]')
    expect(liveTripsSection.exists()).toBe(true)
    expect(liveTripsSection.text()).toContain('En route maintenant (1)')
    expect(liveTripsSection.text()).toContain('Voir tous')
    expect(liveTripsSection.findComponent({ name: 'TripCard' }).exists()).toBe(false)
    expect(
      wrapper.findAllComponents({ name: 'RouterLink' }).some((link) => {
        return (
          link.text() === 'Voir tous' && JSON.stringify(link.props('to')) === '{"name":"trips"}'
        )
      }),
    ).toBe(true)

    const periodDetail = wrapper.find('[data-test="period-detail"]')
    expect(periodDetail.element.tagName).toBe('DETAILS')
    expect((periodDetail.element as HTMLDetailsElement).open).toBe(false)
  })

  it('uses Arabic translations for the final dashboard cards', async () => {
    i18n.global.locale.value = 'ar'
    const wrapper = mount(DashboardView, { global: { plugins: [makeRouter()] } })
    await flushPromises()

    expect(wrapper.text()).toContain('إيرادات الفترة')
    expect(wrapper.text()).toContain('تحصيلات الفترة')
    expect(wrapper.text()).toContain('المصروفات المدفوعة للفترة')
    expect(wrapper.text()).toContain('الربح المحاسبي للفترة')
    expect(wrapper.text()).toContain('الخزينة المتاحة')
    expect(wrapper.text()).toContain('البنوك')
    expect(wrapper.text()).toContain('الصناديق')
    expect(wrapper.text()).toContain('الأرصدة حسب الطرف')
    expect(wrapper.text()).toContain('مخزون الشركة')
    expect(wrapper.text()).toContain('2 رحلة في المخزون حاليًا')
    expect(wrapper.text()).not.toContain("Chiffre d'affaires de la période")
    expect(wrapper.text()).not.toContain('Soldes par partie')
  })
})
