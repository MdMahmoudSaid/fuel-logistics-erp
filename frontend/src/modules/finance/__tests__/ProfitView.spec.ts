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
      shareholders: [],
    })
    fetchReport.mockResolvedValue({
      report_type: 'margin-report',
      fields: [
        'trip_reference',
        'client',
        'product',
        'quantity',
        'supplier_unit_price',
        'transport_cost',
        'customs_cost',
        'transit_cost',
        'border_cost',
        'loading_cost',
        'additional_costs',
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
          supplier_unit_price: '500.0000',
          transport_cost: '2925000.00',
          customs_cost: '10125000.00',
          transit_cost: '450000.00',
          border_cost: '200000.00',
          loading_cost: '100000.00',
          additional_costs: '50000.00',
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
    // period profit = sum of current_margin across rows (one row here)
    expect(wrapper.text()).toContain('2 250 000 XOF')
  })

  it('shows an empty state when the period has no trips', async () => {
    fetchReport.mockResolvedValue({ report_type: 'margin-report', fields: [], rows: [] })
    const wrapper = mount(ProfitView)
    await flushPromises()

    expect(wrapper.text()).toContain('Aucun')
  })
})
