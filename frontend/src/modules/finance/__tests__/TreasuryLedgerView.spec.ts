import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import TreasuryLedgerView from '../TreasuryLedgerView.vue'

const routeQuery: Record<string, string> = {}
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: routeQuery }),
}))

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    treasuryTransactionResource: {
      list: vi.fn(async () => ({ count: 0, next: null, previous: null, results: [] })),
    },
  }
})

const dashboardSummary = vi.fn(async () => ({
  finance: { treasury_balance: '0' },
  bank_amounts: { total: '0' },
  cash_amounts: { total: '0' },
  financial_summary: {
    period_collections: '0',
    period_paid_expenses: '0',
    period_treasury_in: '0',
    period_treasury_out: '0',
  },
}))

vi.mock('@/modules/dashboard/api', () => ({
  fetchDashboardSummary: () => dashboardSummary(),
}))

describe('TreasuryLedgerView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    delete routeQuery.action
  })

  it('shows a Nouvelle avance button next to Nouveau paiement', async () => {
    const wrapper = mount(TreasuryLedgerView)
    await flushPromises()

    const buttons = wrapper.findAll('button').map((button) => button.text())
    expect(buttons).toContain('+ Nouveau paiement')
    expect(buttons).toContain('+ Nouvelle avance')
  })

  it('opens the advance modal when navigated with ?action=advance', async () => {
    routeQuery.action = 'advance'
    const wrapper = mount(TreasuryLedgerView)
    await flushPromises()

    expect(wrapper.findComponent({ name: 'UiModal' }).exists()).toBe(true)
  })

  it('renders the Entrées/sorties card from period_treasury_in/out, not collections/paid_expenses', async () => {
    dashboardSummary.mockResolvedValueOnce({
      finance: { treasury_balance: '10000000' },
      bank_amounts: { total: '10000000' },
      cash_amounts: { total: '0' },
      financial_summary: {
        period_collections: '0',
        period_paid_expenses: '0',
        period_treasury_in: '10000000',
        period_treasury_out: '0',
      },
    })

    const wrapper = mount(TreasuryLedgerView)
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('10 000 000')
  })
})
