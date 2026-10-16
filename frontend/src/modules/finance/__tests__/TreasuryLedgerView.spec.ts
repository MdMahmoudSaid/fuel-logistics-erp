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

const bankAccounts = vi.fn(async () => ({ results: [] as unknown[] }))
const cashAccounts = vi.fn(async () => ({ results: [] as unknown[] }))
vi.mock('@/api/resource', () => ({
  createResourceApi: (path: string) => ({
    list: () => (path === '/bank-accounts/' ? bankAccounts() : cashAccounts()),
  }),
}))

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
    delete routeQuery.type
  })

  it("lists each account's opening balance as an Entrée line, skipping zero balances", async () => {
    bankAccounts.mockResolvedValueOnce({
      results: [
        { id: 1, name: 'BDM', opening_balance: '22872781.00', created_at: '2026-10-10T08:00:00Z' },
        { id: 2, name: 'BNDA', opening_balance: '0.00', created_at: '2026-10-10T08:00:00Z' },
      ],
    })
    cashAccounts.mockResolvedValueOnce({
      results: [
        { id: 3, name: 'Caisse 1', opening_balance: '9600000.00', created_at: '2026-10-11T08:00:00Z' },
      ],
    })
    const wrapper = mount(TreasuryLedgerView)
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain("Solde d'ouverture")
    expect(rows[0].text()).toContain('Caisse 1')
    expect(rows[0].text()).toContain('Entrée')
    expect(rows[1].text()).toContain('BDM')
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

  it('seeds the type filter to Entree when navigated with ?type=in from the dashboard KPI card', async () => {
    routeQuery.type = 'in'
    const wrapper = mount(TreasuryLedgerView)
    await flushPromises()

    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('in')
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
