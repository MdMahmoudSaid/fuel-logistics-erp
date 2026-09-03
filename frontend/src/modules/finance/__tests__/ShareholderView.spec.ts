import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ShareholderView from '../ShareholderView.vue'
import { i18n } from '@/i18n'

// Design doc 2026-08-26-benefices-associes-refinement-design.md: focused
// coverage for what this pass added to the page - the read-only, clearly
// labelled live profit preview banner, and the ledger's new
// available_balance figure. The rest of this large page (CRUD forms,
// distributions, loans, withdrawals) predates this change and has no
// prior test file to extend.

const fetchShareholderLedger = vi.fn()
const fetchShareholderProfitPreview = vi.fn()
const shareholderResourceList = vi.fn()
const shareholderContributionResourceList = vi.fn()

function emptyList() {
  return { count: 0, next: null, previous: null, results: [] }
}

function shareholderListPayload() {
  return {
    count: 1,
    next: null,
    previous: null,
    results: [
      {
        id: 1,
        name: 'Ahmed',
        participation_percent: '100.00',
        contribution: '1000000.00',
        total_contributed: '10000000.00',
        phone: '',
        notes: '',
        is_active: true,
        created_at: '',
        updated_at: '',
      },
    ],
  }
}

vi.mock('../api', () => ({
  shareholderResource: {
    list: (...args: unknown[]) => shareholderResourceList(...args),
    create: vi.fn(),
    update: vi.fn(),
  },
  shareholderLoanResource: { list: vi.fn(async () => emptyList()) },
  shareholderWithdrawalResource: { list: vi.fn(async () => emptyList()) },
  shareholderDistributionResource: { list: vi.fn(async () => emptyList()) },
  shareholderContributionResource: {
    list: (...args: unknown[]) => shareholderContributionResourceList(...args),
  },
  fetchShareholderLedger: (...args: unknown[]) => fetchShareholderLedger(...args),
  fetchShareholderProfitPreview: (...args: unknown[]) => fetchShareholderProfitPreview(...args),
  validateShareholderDistribution: vi.fn(),
  recordShareholderLoanRepayment: vi.fn(),
  createShareholderContribution: vi.fn(),
}))

vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({ list: vi.fn(async () => emptyList()) }),
}))

describe('ShareholderView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    i18n.global.locale.value = 'fr'
    shareholderResourceList.mockResolvedValue(shareholderListPayload())
    shareholderContributionResourceList.mockResolvedValue(emptyList())
    fetchShareholderProfitPreview.mockResolvedValue({
      period_start: '2026-08-01',
      period_end: null,
      // Bug fix (2026-09-03 recette manuelle): operational_profit
      // (900 000) and net_profit (750 000, after 150 000 of general
      // expenses paid) are intentionally different here so a test can
      // tell apart a banner/share wired to the wrong one.
      current_profit: '900000.00',
      operational_profit: '900000.00',
      general_expenses_paid: '150000.00',
      net_profit: '750000.00',
      shareholders: [
        {
          shareholder_id: 1,
          name: 'Ahmed',
          participation_percent: '100.00',
          indicative_share: '750000.00',
        },
      ],
    })
    fetchShareholderLedger.mockResolvedValue({
      shareholder: { id: 1, name: 'Ahmed', participation_percent: '100.00', is_active: true },
      total_amount_due: '1000000.00',
      total_withdrawn: '400000.00',
      remaining_due: '600000.00',
      available_balance: '615000.00',
      total_contributed: '10000000.00',
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
    expect(wrapper.text()).toContain('750 000 XOF')
  })

  // Bug fix (2026-09-03 recette manuelle): the banner used to show
  // preview.current_profit (== operational_profit, 900 000 here) - it must
  // now show preview.net_profit (750 000), matching the same net basis
  // already used by the per-shareholder indicative_share cards right
  // below it, so the two never contradict each other on this page.
  it('shows net profit (not operational profit) in the banner, consistent with the per-shareholder shares', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    const banner = wrapper.findAll('.border-ecart').at(0)
    expect(banner!.text()).toContain('750 000 XOF')
    expect(banner!.text()).not.toContain('900 000 XOF')
    // The per-shareholder share (Ahmed, 100%) must equal the banner's net
    // figure, not the operational one.
    expect(banner!.text()).toContain('Ahmed (100.00%):')
    expect(wrapper.text()).not.toContain('900 000 XOF')
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

  it('shows shareholder contribution in the associates table and form', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === 'Associés')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Contribution')
    expect(wrapper.text()).toContain('1 000 000 XOF')

    await wrapper.findAll('button').find((b) => b.text() === 'Ajouter')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('#contribution').exists()).toBe(true)
  })

  it('localizes the shareholder tabs and indicative summary label in English and Arabic', async () => {
    i18n.global.locale.value = 'en'
    const english = mount(ShareholderView)
    await flushPromises()

    expect(english.text()).toContain('Summary')
    expect(english.text()).toContain('Associates')
    expect(english.text()).toContain('Net indicative profit')
    expect(english.text()).not.toContain('Résumé')
    expect(english.text()).not.toContain('Bénéfice net indicatif')

    english.unmount()
    i18n.global.locale.value = 'ar'
    const arabic = mount(ShareholderView)
    await flushPromises()

    expect(arabic.text()).toContain('ملخص')
    expect(arabic.text()).toContain('الشركاء')
    expect(arabic.text()).toContain('الربح الصافي الإرشادي')
    expect(arabic.text()).not.toContain('Résumé')
    expect(arabic.text()).not.toContain('Bénéfice net indicatif')
  })

  it('shows total_contributed (capital apporte) in the associates table, distinct from the static contribution field', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === 'Associés')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Capital apporté')
    expect(wrapper.text()).toContain('10 000 000 XOF')
  })

  it('refreshes the shareholders list after recording a contribution from the associates tab (bug fix: capital stayed at 0 until reload)', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()
    shareholderResourceList.mockClear()

    await wrapper.findAll('button').find((b) => b.text() === 'Associés')!.trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="new-contribution-button"]').trigger('click')
    await flushPromises()

    const form = wrapper.findComponent({ name: 'ContributionForm' })
    expect(form.exists()).toBe(true)
    form.vm.$emit('success')
    await flushPromises()

    expect(shareholderResourceList).toHaveBeenCalled()
  })

  it("shows the shareholder's capital contribution history in the ledger tab", async () => {
    shareholderContributionResourceList.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 5,
          shareholder: 1,
          shareholder_detail: { id: 1, name: 'Ahmed', participation_percent: '100.00' },
          amount: '10000000.00',
          date: '2026-09-03',
          bank_account: null,
          cash_account: null,
          reference: 'APPORT-1',
          notes: 'Apport initial',
          proof_url: 'https://example.test/proof.jpg',
          recorded_by: null,
          recorded_by_detail: null,
          created_at: '',
          updated_at: '',
        },
      ],
    })

    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === 'Grand livre')!.trigger('click')
    await flushPromises()
    await wrapper.find('#ledger_shareholder').setValue('1')
    await wrapper.findAll('button').find((b) => b.text() === 'Afficher')!.trigger('click')
    await flushPromises()

    expect(shareholderContributionResourceList).toHaveBeenCalledWith({ shareholder: 1 })
    expect(wrapper.text()).toContain('Capital')
    expect(wrapper.text()).toContain('APPORT-1')
    // total_contributed (10 000 000) rendered once for the summary card and
    // once again as the single history row's amount.
    expect(wrapper.text().match(/10 000 000 XOF/g)?.length).toBe(2)
  })

  it('opens the contribution form from the associates tab', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Associés')!
      .trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="new-contribution-button"]').trigger('click')
    await flushPromises()

    expect(wrapper.findComponent({ name: 'ContributionForm' }).exists()).toBe(true)
  })
})
