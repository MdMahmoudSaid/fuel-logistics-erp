import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ShareholderView from '../ShareholderView.vue'

// Design doc 2026-08-26-benefices-associes-refinement-design.md: focused
// coverage for what this pass added to the page - the read-only, clearly
// labelled live profit preview banner, and the ledger's new
// available_balance figure. The rest of this large page (CRUD forms,
// distributions, loans, withdrawals) predates this change and has no
// prior test file to extend.

const fetchShareholderLedger = vi.fn()
const fetchShareholderProfitPreview = vi.fn()

function emptyList() {
  return { count: 0, next: null, previous: null, results: [] }
}

vi.mock('../api', () => ({
  shareholderResource: {
    list: vi.fn(async () => ({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 1,
          name: 'Ahmed',
          participation_percent: '100.00',
          phone: '',
          notes: '',
          is_active: true,
          created_at: '',
          updated_at: '',
        },
      ],
    })),
    create: vi.fn(),
    update: vi.fn(),
  },
  shareholderLoanResource: { list: vi.fn(async () => emptyList()) },
  shareholderWithdrawalResource: { list: vi.fn(async () => emptyList()) },
  shareholderDistributionResource: { list: vi.fn(async () => emptyList()) },
  fetchShareholderLedger: (...args: unknown[]) => fetchShareholderLedger(...args),
  fetchShareholderProfitPreview: (...args: unknown[]) => fetchShareholderProfitPreview(...args),
  validateShareholderDistribution: vi.fn(),
  recordShareholderLoanRepayment: vi.fn(),
}))

vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({ list: vi.fn(async () => emptyList()) }),
}))

describe('ShareholderView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchShareholderProfitPreview.mockResolvedValue({
      period_start: '2026-08-01',
      period_end: null,
      current_profit: '900000.00',
      shareholders: [
        {
          shareholder_id: 1,
          name: 'Ahmed',
          participation_percent: '100.00',
          indicative_share: '900000.00',
        },
      ],
    })
    fetchShareholderLedger.mockResolvedValue({
      shareholder: { id: 1, name: 'Ahmed', participation_percent: '100.00', is_active: true },
      total_amount_due: '1000000.00',
      total_withdrawn: '400000.00',
      remaining_due: '600000.00',
      available_balance: '615000.00',
      shares: [],
      loans_borrowed: [],
      loans_lent: [
        {
          id: 1,
          borrower_id: 2,
          borrower_name: 'Other',
          amount: '15000.00',
          amount_repaid: '0.00',
          remaining_amount: '15000.00',
          status: 'OPEN',
          date: '2026-08-01',
        },
      ],
      net_loan_balance: '15000.00',
      withdrawals: [],
    })
  })

  it('shows the live profit preview as clearly indicative, never as a confirmed distribution', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    expect(fetchShareholderProfitPreview).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Indicatif')
    expect(wrapper.text()).toContain('900 000 XOF')
  })

  it("loads a shareholder's ledger and shows the combined available_balance", async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === 'Grand livre')!.trigger('click')
    await flushPromises()

    await wrapper.find('#ledger_shareholder').setValue('1')
    const viewButton = wrapper.findAll('button').find((b) => b.text() === 'Afficher')
    expect(viewButton).toBeTruthy()
    await viewButton!.trigger('click')
    await flushPromises()

    expect(fetchShareholderLedger).toHaveBeenCalledWith(1)
    // available_balance (615000) is distinct from remaining_due (600000)
    // and net_loan_balance (15000) alone - proves the combined figure
    // renders, not just its two components separately.
    expect(wrapper.text()).toContain('615 000 XOF')
  })
})
