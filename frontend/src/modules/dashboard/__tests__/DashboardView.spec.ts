import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import DashboardView from '../DashboardView.vue'
import type { DashboardSummary } from '../types'

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

describe('DashboardView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads the default range on mount and renders all 6 KPI sections', async () => {
    const wrapper = mount(DashboardView)
    await flushPromises()

    expect(fetchDashboardSummary).toHaveBeenCalledWith({ range: 'month' })
    expect(wrapper.text()).toContain('Operations')
    expect(wrapper.text()).toContain('Fuel')
    expect(wrapper.text()).toContain('Sales')
    expect(wrapper.text()).toContain('Transport')
    expect(wrapper.text()).toContain('Finance')
    expect(wrapper.text()).toContain('Profit')
    expect(wrapper.text()).toContain('225,000')
    expect(wrapper.text()).toContain('1,957,500')
  })

  it('shows an error message when the summary fails to load', async () => {
    fetchDashboardSummary.mockRejectedValueOnce(new Error('network error'))
    const wrapper = mount(DashboardView)
    await flushPromises()

    expect(wrapper.text()).toContain('Could not load the dashboard.')
  })
})
