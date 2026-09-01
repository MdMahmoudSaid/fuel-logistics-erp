import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import TransporterLedgerView from '../TransporterLedgerView.vue'
import type { TransporterLedger } from '../types'

const push = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '1' } }),
  useRouter: () => ({ push }),
}))

const ledger: TransporterLedger = {
  transporter: { id: 1, name: 'Trans SA', company_name: '' },
  gross_amount: '700000.00',
  deductions: '0.00',
  advances_applied: '100000.00',
  settled: '0.00',
  net_outstanding: '600000.00',
  unsettled_advances: '0.00',
  payments: [
    {
      id: 1, trip: 1, trip_reference: 'TRIP-001', transporter: 1, transporter_detail: null,
      calculation_method: 'FIXED', base_amount: '700000.00', unit_price_per_litre: null,
      deduction_amount: '0.00', advance_applied: null, net_amount: '600000.00', status: 'PAYABLE',
      created_at: '', updated_at: '',
    },
  ],
  advances: [
    {
      id: 1, transporter: 1, transporter_detail: null, bank_account: null, cash_account: 1,
      amount: '100000.00', date: '2026-08-17', reference: 'TADV-1', notes: '',
      proof_url: null, remaining_amount: '0.00', settled: true, created_at: '', updated_at: '',
    },
  ],
  summary: {
    id: 1, label: 'Trans SA',
    total_due: '600000.00', open_advances: '0.00', net_balance: '-600000.00',
    last_advance: { date: '2026-08-17', amount: '100000.00' },
    last_payment: null,
  },
  entries: [
    { type: 'advance_given', date: '2026-08-17', amount: '100000.00', reference: 'TADV-1', note: '', proof_url: null },
    { type: 'debt_created', date: '2026-08-18', amount: '700000.00', reference: 'TRIP-001', note: '', proof_url: null },
    { type: 'advance_consumed', date: '2026-08-18', amount: '100000.00', reference: 'TADV-1', note: '', proof_url: null },
  ],
}

const fetchTransporterLedger = vi.fn(async () => ledger)

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return { ...actual, fetchTransporterLedger: (...args: unknown[]) => fetchTransporterLedger(...(args as [])) }
})

describe('TransporterLedgerView', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows a Nouvelle avance button (not Nouveau paiement) when net_balance is negative and there IS an open debt', async () => {
    // net_balance < 0 means a real debt is owed -> Nouveau paiement, not Nouvelle avance
    const wrapper = mount(TransporterLedgerView)
    await flushPromises()

    const buttons = wrapper.findAll('button').map((button) => button.text())
    expect(buttons).toContain('Enregistrer un paiement')
    expect(buttons).not.toContain('Nouvelle avance')
  })

  it('shows the 4 balance cards and the chronological entries table', async () => {
    const wrapper = mount(TransporterLedgerView)
    await flushPromises()

    expect(wrapper.text()).toContain('Total dû')
    expect(wrapper.text()).toContain('Avances ouvertes')
    expect(wrapper.text()).toContain('Solde net')
    expect(wrapper.text()).toContain('Avance versée')
    expect(wrapper.text()).toContain('Dette créée')
    expect(wrapper.text()).toContain('Avance imputée')
  })
})
