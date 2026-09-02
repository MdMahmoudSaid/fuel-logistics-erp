import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ProfitView from '../ProfitView.vue'

// Design doc 2026-08-26-benefices-associes-refinement-design.md: the
// Benefices page reuses GET /api/reports/margin-report/ (already tested
// end to end in apps/reports/test_queries.py) rather than a new backend
// endpoint - this test only covers the page's own logic: period-triggered
// fetch, per-trip table rendering, and the indicative preview banner.

const fetchReport = vi.fn()
const fetchShareholderProfitPreview = vi.fn()

vi.mock('@/modules/reports/api', () => ({
  fetchReport: (...args: unknown[]) => fetchReport(...args),
}))

vi.mock('../api', () => ({
  fetchShareholderProfitPreview: (...args: unknown[]) => fetchShareholderProfitPreview(...args),
}))

describe('ProfitView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchShareholderProfitPreview.mockResolvedValue({
      period_start: '2026-08-01',
      period_end: null,
      current_profit: '900000.00',
      operational_profit: '900000.00',
      general_expenses_paid: '150000.00',
      net_profit: '750000.00',
      shareholders: [],
    })
    fetchReport.mockResolvedValue({
      report_type: 'margin-report',
      fields: [
        'trip_reference',
        'client',
        'product',
        'quantity',
        'quantity_loaded',
        'quantity_invoiced',
        'transporter_loss_quantity',
        'transporter_loss_indemnity',
        'supplier_unit_price',
        'transport_cost',
        'customs_cost',
        'transit_cost',
        'border_cost',
        'loading_cost',
        'additional_costs',
        'real_total_cost',
        'unit_cost',
        'unit_selling_price',
        'unit_profit',
        'current_margin',
      ],
      rows: [
        {
          trip_reference: 'TRIP-1',
          client: 'Client A',
          product: 'Gasoil',
          quantity: '45000.00',
          quantity_loaded: '45000.00',
          quantity_invoiced: '44900.00',
          transporter_loss_quantity: '100.00',
          transporter_loss_indemnity: '90000.00',
          supplier_unit_price: '500.0000',
          transport_cost: '2925000.00',
          customs_cost: '10125000.00',
          transit_cost: '450000.00',
          border_cost: '200000.00',
          loading_cost: '100000.00',
          additional_costs: '50000.00',
          real_total_cost: '36000000.00',
          unit_cost: '800.0000',
          unit_selling_price: '850.0000',
          unit_profit: '50.0000',
          current_margin: '2250000.00',
        },
      ],
    })
  })

  it('loads the profit-by-trip breakdown on period change and renders totals', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()

    // The period filter triggers the load - simulate the DateRangeFilter's
    // default emit (it auto-applies "month" onMounted).
    await flushPromises()

    expect(fetchShareholderProfitPreview).toHaveBeenCalled()
    expect(wrapper.text()).toContain('TRIP-1')
    expect(wrapper.text()).toContain('Client A')
    expect(wrapper.text()).toContain('90 000 XOF')
    // period profit = sum of current_margin across rows (one row here)
    expect(wrapper.text()).toContain('2 250 000 XOF')
  })

  it('clarifies accounting, received, and distributable profit meanings', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()

    expect(wrapper.findAll('[data-test="profit-summary-card"]')).toHaveLength(3)
    expect(wrapper.text()).toContain('Bénéfice opérationnel')
    expect(wrapper.text()).toContain('Bénéfice encaissé')
    expect(wrapper.text()).toContain('Bénéfice distribuable')
    expect(wrapper.text()).toContain(
      "Le bénéfice comptable n'est pas automatiquement distribuable.",
    )
  })

  it('shows operational profit, general expenses paid, and net profit from the preview', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()

    expect(wrapper.text()).toContain('Bénéfice opérationnel')
    expect(wrapper.text()).toContain('Dépenses générales payées')
    expect(wrapper.text()).toContain('Bénéfice net')
    expect(wrapper.text()).toContain('150 000 XOF')
    expect(wrapper.text()).toContain('750 000 XOF')
  })

  it('renders dashboard-style cost cards with icons and tabular aligned amounts', async () => {
    const wrapper = mount(ProfitView)
    await flushPromises()

    const cards = wrapper.findAll('[data-test="profit-cost-card"]')
    expect(cards).toHaveLength(8)
    expect(cards[0]!.classes()).toEqual(
      expect.arrayContaining(['border-ligne', 'rounded-lg', 'border', 'bg-white', 'p-4']),
    )
    expect(cards[0]!.find('svg').exists()).toBe(true)
    expect(cards[0]!.find('.font-mono.tabular-nums').exists()).toBe(true)
  })

  it('shows an empty state when the period has no trips', async () => {
    fetchReport.mockResolvedValue({ report_type: 'margin-report', fields: [], rows: [] })
    const wrapper = mount(ProfitView)
    await flushPromises()

    expect(wrapper.text()).toContain('Aucun')
  })

  it('colors per-trip unit and total profit by sign', async () => {
    fetchReport.mockResolvedValue({
      report_type: 'margin-report',
      fields: [],
      rows: [
        {
          trip_reference: 'TRIP-POS',
          client: 'Client A',
          product: 'Gasoil',
          quantity: '1000.00',
          quantity_loaded: '1000.00',
          quantity_invoiced: '1000.00',
          transporter_loss_quantity: '0.00',
          transporter_loss_indemnity: '0.00',
          supplier_unit_price: '500.0000',
          transport_cost: '0.00',
          customs_cost: '0.00',
          transit_cost: '0.00',
          border_cost: '0.00',
          loading_cost: '0.00',
          additional_costs: '0.00',
          real_total_cost: '630000.00',
          unit_cost: '630.0000',
          unit_selling_price: '640.0000',
          unit_profit: '10.0000',
          current_margin: '10000.00',
        },
        {
          trip_reference: 'TRIP-NEG',
          client: 'Client B',
          product: 'Gasoil',
          quantity: '1000.00',
          quantity_loaded: '1000.00',
          quantity_invoiced: '1000.00',
          transporter_loss_quantity: '0.00',
          transporter_loss_indemnity: '0.00',
          supplier_unit_price: '500.0000',
          transport_cost: '0.00',
          customs_cost: '0.00',
          transit_cost: '0.00',
          border_cost: '0.00',
          loading_cost: '0.00',
          additional_costs: '0.00',
          real_total_cost: '650000.00',
          unit_cost: '650.0000',
          unit_selling_price: '640.0000',
          unit_profit: '-10.0000',
          current_margin: '-10000.00',
        },
        {
          trip_reference: 'TRIP-ZERO',
          client: 'Client C',
          product: 'Gasoil',
          quantity: '1000.00',
          quantity_loaded: '1000.00',
          quantity_invoiced: '1000.00',
          transporter_loss_quantity: '0.00',
          transporter_loss_indemnity: '0.00',
          supplier_unit_price: '500.0000',
          transport_cost: '0.00',
          customs_cost: '0.00',
          transit_cost: '0.00',
          border_cost: '0.00',
          loading_cost: '0.00',
          additional_costs: '0.00',
          real_total_cost: '640000.00',
          unit_cost: '640.0000',
          unit_selling_price: '640.0000',
          unit_profit: '0.0000',
          current_margin: '0.00',
        },
      ],
    })
    const wrapper = mount(ProfitView)
    await flushPromises()

    const bodyRows = wrapper.findAll('tbody tr')
    const [posRow, negRow, zeroRow] = bodyRows
    const profitCells = (row: (typeof bodyRows)[number]) =>
      row
        .findAll('td')
        .slice(-2)
        .map((td) => td.find('span'))

    const [posUnit, posTotal] = profitCells(posRow!)
    expect(posUnit!.classes()).toContain('text-livre')
    expect(posTotal!.classes()).toContain('text-livre')

    const [negUnit, negTotal] = profitCells(negRow!)
    expect(negUnit!.classes()).toContain('text-critique')
    expect(negTotal!.classes()).toContain('text-critique')

    const [zeroUnit, zeroTotal] = profitCells(zeroRow!)
    expect(zeroUnit!.classes()).not.toContain('text-livre')
    expect(zeroUnit!.classes()).not.toContain('text-critique')
    expect(zeroTotal!.classes()).not.toContain('text-livre')
    expect(zeroTotal!.classes()).not.toContain('text-critique')
  })
})
