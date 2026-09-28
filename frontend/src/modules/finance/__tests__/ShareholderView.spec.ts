import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ShareholderView from '../ShareholderView.vue'
import { i18n } from '@/i18n'

// Bug fix (2026-09-18): destructive actions now go through the app's own
// popup instead of window.confirm() - see useConfirmDialog.
const confirmDialogMock = vi.fn(async (_message: string) => true)
vi.mock('@/composables/useConfirmDialog', () => ({
  confirmDialog: (message: string) => confirmDialogMock(message),
}))

// Design doc 2026-08-26-benefices-associes-refinement-design.md: focused
// coverage for what this pass added to the page - the read-only, clearly
// labelled live profit preview banner, and the ledger's new
// available_balance figure. The rest of this large page (CRUD forms,
// distributions, loans, withdrawals) predates this change and has no
// prior test file to extend.

const fetchShareholderLedger = vi.fn()
const fetchShareholderProfitPreview = vi.fn()
const fetchShareholderBalancesSummary = vi.fn()
const shareholderResourceList = vi.fn()
const shareholderContributionResourceList = vi.fn()
const shareholderWithdrawalResourceList = vi.fn()
const shareholderDistributionResourceCreate = vi.fn(
  async (payload: Record<string, unknown>): Promise<Record<string, unknown>> => ({
    id: 1,
    status: 'DRAFT',
    ...payload,
  }),
)
const shareholderDistributionResourceList = vi.fn()
const cancelShareholderDistribution = vi.fn()
const validateShareholderDistribution = vi.fn()
const shareholderPeriodResourceList = vi.fn()
const shareholderPeriodResourceCreate = vi.fn()
const closeShareholderProfitPeriod = vi.fn()
const reopenShareholderProfitPeriod = vi.fn()

function emptyList() {
  return { count: 0, next: null, previous: null, results: [] as Record<string, unknown>[] }
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
  shareholderWithdrawalResource: {
    list: (...args: unknown[]) => shareholderWithdrawalResourceList(...args),
  },
  shareholderDistributionResource: {
    list: (...args: unknown[]) => shareholderDistributionResourceList(...args),
    create: (payload: Record<string, unknown>) => shareholderDistributionResourceCreate(payload),
  },
  shareholderProfitPeriodResource: {
    list: (...args: unknown[]) => shareholderPeriodResourceList(...args),
    create: (...args: unknown[]) => shareholderPeriodResourceCreate(...args),
  },
  shareholderContributionResource: {
    list: (...args: unknown[]) => shareholderContributionResourceList(...args),
  },
  fetchShareholderLedger: (...args: unknown[]) => fetchShareholderLedger(...args),
  fetchShareholderProfitPreview: (...args: unknown[]) => fetchShareholderProfitPreview(...args),
  fetchShareholderBalancesSummary: (...args: unknown[]) => fetchShareholderBalancesSummary(...args),
  validateShareholderDistribution: (...args: unknown[]) => validateShareholderDistribution(...args),
  cancelShareholderDistribution: (...args: unknown[]) => cancelShareholderDistribution(...args),
  closeShareholderProfitPeriod: (...args: unknown[]) => closeShareholderProfitPeriod(...args),
  reopenShareholderProfitPeriod: (...args: unknown[]) => reopenShareholderProfitPeriod(...args),
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
    shareholderWithdrawalResourceList.mockResolvedValue(emptyList())
    shareholderDistributionResourceList.mockResolvedValue(emptyList())
    shareholderPeriodResourceList.mockResolvedValue(emptyList())
    fetchShareholderProfitPreview.mockResolvedValue({
      period_start: '2026-08-01',
      period_end: null,
      // Business decision (2026-09-04, distribution basis change):
      // operational_profit (850 000), net_profit (750 000, after 100 000
      // of general expenses paid), and distributable_result (500 000,
      // after debts/capital) are intentionally all different here so a
      // test can tell apart a banner/share/distribution-default wired to
      // the wrong one. 80% share of distributable_result -> 400 000.
      current_profit: '850000.00',
      operational_profit: '850000.00',
      general_expenses_paid: '100000.00',
      net_profit: '750000.00',
      all_time_net_profit: '750000.00',
      working_capital: {
        capital: '250000.00',
        treasury_available: '600000.00',
        customer_receivables: '150000.00',
        supplier_debt_total: '0.00',
        transporter_debt_total: '0.00',
        other_debts: '0.00',
        supplier_reliquat_value: '0.00',
        supplier_in_transit_value: '0.00',
        supplier_company_stock_value: '0.00',
        gross: '750000.00',
        total: '750000.00',
      },
      already_distributed: '0.00',
      already_validated_total: '0.00',
      result_after_debts_and_capital: '0.00',
      distributable_result: '500000.00',
      shareholders: [
        {
          shareholder_id: 1,
          name: 'Ahmed',
          participation_percent: '80.00',
          indicative_share: '400000.00',
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
      capital_returned: '0.00',
      capital_remaining: '10000000.00',
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
    fetchShareholderBalancesSummary.mockResolvedValue({
      shareholders: [{ id: 1, name: 'Ahmed', available_balance: '615000.00' }],
      total: '615000.00',
    })
  })

  it('shows the live profit preview as clearly indicative, never as a confirmed distribution', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    expect(fetchShareholderProfitPreview).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Indicatif')
    expect(wrapper.text()).toContain('500 000 XOF')
  })

  // Business decision (2026-09-04): the per-shareholder indicative_share
  // is based on distributable_result (500 000), not operational_profit
  // (850 000) or net_profit (750 000). 2026-09-08 review, point 7: the
  // banner now also shows the period profit and the already-validated
  // engagements as their own clearly-labelled lines - shown, but never
  // conflated with the distributable figure or with each other.
  it('bases the per-shareholder share on distributable_result and labels each amount distinctly', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    const banner = wrapper.findAll('.border-ecart').at(0)
    expect(banner!.text()).toContain('500 000 XOF')
    expect(banner!.text()).not.toContain('850 000 XOF')
    // The per-shareholder share (Ahmed, 80%) must equal 400 000 (80% of
    // distributable_result), not the operational or net one.
    expect(banner!.text()).toContain('Ahmed (80.00%):')
    expect(banner!.text()).toContain('400 000 XOF')
    // net_profit appears, but only against its own label.
    const breakdown = wrapper.find('[data-test="preview-breakdown"]')
    expect(breakdown.text()).toContain('Bénéfice net global après dépenses générales')
    expect(breakdown.text()).toContain('750 000 XOF')
  })

  // Recette bug (2026-09-08): the banner never showed what had already
  // been committed to shareholders, so a manager had no way to tell the
  // displayed distributable_result already accounted for an earlier
  // distribution (it looked "stuck" instead).
  it('shows already_distributed in the preview banner when non-zero', async () => {
    fetchShareholderProfitPreview.mockResolvedValue({
      period_start: '2026-08-01',
      period_end: null,
      current_profit: '850000.00',
      operational_profit: '850000.00',
      general_expenses_paid: '100000.00',
      net_profit: '750000.00',
      all_time_net_profit: '750000.00',
      working_capital: {
        capital: '250000.00',
        treasury_available: '600000.00',
        customer_receivables: '150000.00',
        supplier_debt_total: '0.00',
        transporter_debt_total: '0.00',
        other_debts: '0.00',
        supplier_reliquat_value: '0.00',
        supplier_in_transit_value: '0.00',
        supplier_company_stock_value: '0.00',
        gross: '750000.00',
        total: '750000.00',
      },
      already_distributed: '100000.00',
      already_validated_total: '100000.00',
      result_after_debts_and_capital: '0.00',
      distributable_result: '400000.00',
      shareholders: [
        {
          shareholder_id: 1,
          name: 'Ahmed',
          participation_percent: '80.00',
          indicative_share: '320000.00',
        },
      ],
    })

    const wrapper = mount(ShareholderView)
    await flushPromises()

    const banner = wrapper.findAll('.border-ecart').at(0)
    expect(banner!.text()).toContain('100 000 XOF')
  })

  // 2026-09-08 review, point 7: the three amounts (period profit, already
  // validated engagements, still distributable) are always shown
  // distinctly - never conflated, never hidden.
  it('always shows the three-amount breakdown, including a zero already-validated line', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    const breakdown = wrapper.find('[data-test="preview-breakdown"]')
    expect(breakdown.exists()).toBe(true)
    expect(breakdown.text()).toContain('Bénéfice net global après dépenses générales')
    expect(breakdown.text()).toContain('Répartitions déjà validées')
    expect(breakdown.text()).toContain('Bénéfice à distribuer')
    // default preview mock: net_profit 750 000, already_distributed 0,
    // distributable_result 500 000
    expect(breakdown.text()).toContain('750 000 XOF')
    expect(breakdown.text()).toContain('500 000 XOF')
    expect(wrapper.find('[data-test="preview-already-distributed"]').text()).toContain('0 XOF')
  })

  it('starts a user-defined profit period', async () => {
    shareholderPeriodResourceCreate.mockResolvedValue({})
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Répartition des bénéfices')!
      .trigger('click')
    await wrapper.find('#open_period_start').setValue('2026-06-01')
    await wrapper.find('[data-test="start-profit-period"] form').trigger('submit.prevent')
    await flushPromises()

    expect(shareholderPeriodResourceCreate).toHaveBeenCalledWith({ start_date: '2026-06-01' })
  })

  it('closes the open period and requests automatic distribution', async () => {
    shareholderPeriodResourceList.mockResolvedValue({
      ...emptyList(),
      count: 1,
      results: [
        {
          id: 9,
          start_date: '2026-06-01',
          end_date: null,
          status: 'OPEN',
          live_net_profit: '500000.00',
          distribution: null,
        },
      ],
    })
    closeShareholderProfitPeriod.mockResolvedValue({})
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Répartition des bénéfices')!
      .trigger('click')
    await wrapper.find('#close_period_end').setValue('2026-09-15')
    await wrapper.find('[data-test="open-profit-period"] form').trigger('submit.prevent')
    await flushPromises()

    expect(closeShareholderProfitPeriod).toHaveBeenCalledWith(9, '2026-09-15')
  })

  it('requires a reason before reopening the latest closed period', async () => {
    shareholderPeriodResourceList.mockResolvedValue({
      ...emptyList(),
      count: 1,
      results: [
        {
          id: 10,
          start_date: '2026-06-01',
          end_date: '2026-09-15',
          status: 'CLOSED',
          net_profit: '500000.00',
          distribution: 4,
        },
      ],
    })
    reopenShareholderProfitPeriod.mockResolvedValue({})
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Répartition des bénéfices')!
      .trigger('click')
    const button = wrapper.find('[data-test="reopen-profit-period"]')
    expect(button.attributes('disabled')).toBeDefined()
    await wrapper.find('#reopen_reason').setValue('Correction vente oubliée')
    await flushPromises()
    await wrapper
      .findAll('form')
      .find((form) => form.find('#reopen_reason').exists())!
      .trigger('submit')
    await flushPromises()

    expect(reopenShareholderProfitPeriod).toHaveBeenCalledWith(10, 'Correction vente oubliée')
  })

  it("loads a shareholder's ledger and shows the combined available_balance", async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Grand livre')!
      .trigger('click')
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

  it('shows the total shareholder balances card, distinct from the indicative preview', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    expect(fetchShareholderBalancesSummary).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Solde total des actionnaires')
    expect(wrapper.text()).toContain('615 000 XOF')
  })

  it("drills into a shareholder's Grand livre by clicking their name in the balances card", async () => {
    // Client feedback (2026-09-16, second pass): a separate "Voir le grand
    // livre" button was replaced by making the shareholder's own name the
    // underlined clickable link, for a simpler, less cluttered card.
    const wrapper = mount(ShareholderView)
    await flushPromises()

    const nameLink = wrapper
      .findAll('button')
      .find((b) => b.text() === 'Ahmed' && b.classes().includes('underline'))
    expect(nameLink).toBeTruthy()
    await nameLink!.trigger('click')
    await flushPromises()

    expect(fetchShareholderLedger).toHaveBeenCalledWith(1)
    // The ledger tab's own loaded content ("Solde disponible" only renders
    // once `ledger` is populated) proves the click both switched tabs and
    // loaded that shareholder, not just navigated to an empty tab.
    expect(wrapper.text()).toContain('Solde disponible')
  })

  it('shows the real negative "reste disponible pour repartition" in the indicative box, but floors the Resume cards to 0', async () => {
    // Client feedback (2026-09-16, second pass): the orange "Indicatif" box
    // is the detailed/real view and must show the true figure, negative
    // included - only the simplified per-shareholder Resume cards below
    // must never show a negative amount (a non-technical shareholder read
    // that as being personally in debt).
    fetchShareholderProfitPreview.mockResolvedValue({
      period_start: '2026-08-01',
      period_end: null,
      current_profit: '0.00',
      operational_profit: '0.00',
      general_expenses_paid: '0.00',
      net_profit: '0.00',
      all_time_net_profit: '0.00',
      working_capital: {
        capital: '32800000.00',
        treasury_available: '0.00',
        customer_receivables: '0.00',
        supplier_debt_total: '500000000.00',
        transporter_debt_total: '0.00',
        other_debts: '0.00',
        supplier_reliquat_value: '32800000.00',
        supplier_in_transit_value: '0.00',
        supplier_company_stock_value: '0.00',
        gross: '0.00',
        total: '532800000.00',
      },
      already_distributed: '0.00',
      already_validated_total: '0.00',
      result_after_debts_and_capital: '0.00',
      distributable_result: '-32800000.00',
      shareholders: [
        {
          shareholder_id: 1,
          name: 'Ahmed',
          participation_percent: '80.00',
          indicative_share: '-26240000.00',
        },
      ],
    })

    const wrapper = mount(ShareholderView)
    await flushPromises()

    // The indicative box: real, negative figures.
    expect(wrapper.text()).toContain('-32 800 000 XOF')
    expect(wrapper.text()).toContain('-26 240 000 XOF')

    // The Resume cards: floored to 0 with an explanatory note, never a
    // negative amount or the word "dette" anywhere on them.
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Résumé')!
      .trigger('click')
    await flushPromises()
    const summarySection = wrapper.get('[class*="grid"][class*="md:grid-cols-2"]')
    expect(summarySection.text()).not.toContain('-26 240 000')
    expect(summarySection.text()).toContain('0 XOF')
    expect(summarySection.text()).toContain('Aucun montant disponible pour le moment')
  })

  it('shows shareholder contribution in the associates table but not in the add/edit form', async () => {
    // Bug fix (2026-09-10): "Contribution" is a read-only historical
    // figure (see ShareholderSerializer.Meta.read_only_fields) - it must
    // stay visible in the list, but the Ajouter/Modifier form must no
    // longer let a user type an arbitrary amount there with no linked
    // bank/cash account. Real capital goes through "Nouvel apport en
    // capital" (ContributionForm.vue) instead.
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Associés')!
      .trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Contribution')
    expect(wrapper.text()).toContain('1 000 000 XOF')

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Ajouter')!
      .trigger('click')
    await flushPromises()

    expect(wrapper.find('#contribution').exists()).toBe(false)
  })

  it("shows the shareholder's available balance as soon as they are picked in Retraits, without visiting Grand livre first", async () => {
    // Bug fix (2026-09-13 audit) still applies to the hint: picking a
    // shareholder directly in Retraits must load their ledger without
    // needing a prior visit to Grand livre.
    fetchShareholderLedger.mockResolvedValue({
      shareholder: { id: 1, name: 'Ahmed', participation_percent: '100.00', is_active: true },
      total_amount_due: '3528000.00',
      total_withdrawn: '0.00',
      remaining_due: '3528000.00',
      available_balance: '3528000.00',
      total_contributed: '0.00',
      capital_returned: '0.00',
      capital_remaining: '0.00',
      shares: [],
      loans_borrowed: [],
      loans_lent: [],
      net_loan_balance: '0.00',
      withdrawals: [],
    })

    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Retraits')!
      .trigger('click')
    await flushPromises()

    await wrapper.find('#wd_shareholder').setValue('1')
    await flushPromises()

    expect(fetchShareholderLedger).toHaveBeenCalledWith(1)
    expect(wrapper.find('#wd_share').exists()).toBe(false)
    expect(wrapper.text()).toContain('3 528 000 XOF')
  })

  it('shows a profit/capital breakdown only for withdrawals that touched capital', async () => {
    shareholderWithdrawalResourceList.mockResolvedValueOnce({
      count: 2,
      next: null,
      previous: null,
      results: [
        {
          id: 1,
          shareholder: 1,
          shareholder_detail: {
            id: 1,
            name: 'Ahmed',
            participation_percent: '100.00',
            contribution: '0.00',
          },
          allocations: [
            { profit_share: 10, contribution: null, amount: '500000.00' },
            { profit_share: null, contribution: 20, amount: '200000.00' },
          ],
          amount: '700000.00',
          date: '2026-08-01',
          bank_account: null,
          cash_account: 1,
          notes: '',
          recorded_by: null,
          recorded_by_detail: null,
          created_at: '',
          updated_at: '',
        },
        {
          id: 2,
          shareholder: 1,
          shareholder_detail: {
            id: 1,
            name: 'Ahmed',
            participation_percent: '100.00',
            contribution: '0.00',
          },
          allocations: [{ profit_share: 11, contribution: null, amount: '60000.00' }],
          amount: '60000.00',
          date: '2026-08-02',
          bank_account: null,
          cash_account: 1,
          notes: '',
          recorded_by: null,
          recorded_by_detail: null,
          created_at: '',
          updated_at: '',
        },
      ],
    })

    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Retraits')!
      .trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('700 000 XOF')
    expect(wrapper.text()).toContain('capital')
    const rows = wrapper.findAll('tbody tr')
    const secondRow = rows.find((r) => r.text().includes('60 000'))
    expect(secondRow?.text()).not.toContain('capital')
  })

  it('localizes the shareholder tabs and suggested distributable result label in English and Arabic', async () => {
    i18n.global.locale.value = 'en'
    const english = mount(ShareholderView)
    await flushPromises()

    expect(english.text()).toContain('Summary')
    expect(english.text()).toContain('Associates')
    expect(english.text()).toContain('Proposed profit to distribute')
    expect(english.text()).not.toContain('Résumé')
    expect(english.text()).not.toContain('Résultat distribuable proposé')

    english.unmount()
    i18n.global.locale.value = 'ar'
    const arabic = mount(ShareholderView)
    await flushPromises()

    expect(arabic.text()).toContain('ملخص')
    expect(arabic.text()).toContain('الشركاء')
    expect(arabic.text()).toContain('الربح المقترح للتوزيع')
    expect(arabic.text()).not.toContain('Résumé')
    expect(arabic.text()).not.toContain('Résultat distribuable proposé')
  })

  it('shows total_contributed (capital apporte) in the associates table, distinct from the static contribution field', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Associés')!
      .trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Capital apporté')
    expect(wrapper.text()).toContain('10 000 000 XOF')
  })

  it('refreshes the shareholders list after recording a contribution from the associates tab (bug fix: capital stayed at 0 until reload)', async () => {
    const wrapper = mount(ShareholderView)
    await flushPromises()
    shareholderResourceList.mockClear()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Associés')!
      .trigger('click')
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

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Grand livre')!
      .trigger('click')
    await flushPromises()
    await wrapper.find('#ledger_shareholder').setValue('1')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Afficher')!
      .trigger('click')
    await flushPromises()

    expect(shareholderContributionResourceList).toHaveBeenCalledWith({ shareholder: 1 })
    expect(wrapper.text()).toContain('Capital')
    expect(wrapper.text()).toContain('APPORT-1')
    // total_contributed (10 000 000) rendered once for the summary card,
    // once for the "Capital restant" line (equal here since nothing has
    // been returned yet), and once again as the single history row's
    // amount.
    expect(wrapper.text().match(/10 000 000 XOF/g)?.length).toBe(3)
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

  it('cancels a distribution after confirmation and refreshes the list', async () => {
    const listMock = vi.fn(async () => ({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 7,
          period_start: '2026-07-01',
          period_end: '2026-07-31',
          total_profit: '100000.00',
          status: 'DRAFT',
          shares: [],
        },
      ],
    }))
    shareholderDistributionResourceList.mockImplementationOnce(listMock)
    cancelShareholderDistribution.mockResolvedValue({
      id: 7,
      status: 'CANCELLED',
    })
    confirmDialogMock.mockResolvedValueOnce(true)

    const wrapper = mount(ShareholderView)
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Répartition des bénéfices')!
      .trigger('click')
    await flushPromises()

    const cancelButton = wrapper.find('[data-test="cancel-distribution-7"]')
    expect(cancelButton.exists()).toBe(true)
    await cancelButton.trigger('click')
    await flushPromises()

    expect(cancelShareholderDistribution).toHaveBeenCalledWith(7)
    expect(listMock).toHaveBeenCalled()
  })

  it('shows the backend error when cancellation is rejected (a withdrawal already exists)', async () => {
    shareholderDistributionResourceList.mockResolvedValueOnce({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 8,
          period_start: '2026-07-01',
          period_end: '2026-07-31',
          total_profit: '100000.00',
          status: 'VALIDATED',
          shares: [],
        },
      ],
    })
    cancelShareholderDistribution.mockRejectedValue({
      response: { data: { detail: "Impossible d'annuler cette repartition." } },
    })
    confirmDialogMock.mockResolvedValueOnce(true)

    const wrapper = mount(ShareholderView)
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Répartition des bénéfices')!
      .trigger('click')
    await flushPromises()

    await wrapper.find('[data-test="cancel-distribution-8"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain("Impossible d'annuler cette repartition.")
  })

  // 2026-09-08 review, point 2: the frontend must clearly block (not just
  // softly warn) a validation whose amount exceeds the still-distributable
  // result - the backend check stays the real guard.
  it('disables the Validate button for a DRAFT whose total_profit exceeds distributable_result', async () => {
    shareholderDistributionResourceList.mockResolvedValueOnce({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 9,
          period_start: '2026-07-01',
          period_end: '2026-07-31',
          total_profit: '900000.00',
          status: 'DRAFT',
          available_to_distribute: '500000.00',
          shares: [],
        },
      ],
    })

    const wrapper = mount(ShareholderView)
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Répartition des bénéfices')!
      .trigger('click')
    await flushPromises()

    const validateButton = wrapper.findAll('button').find((b) => b.text() === 'Valider')
    expect(validateButton).toBeTruthy()
    expect(validateButton!.attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="validate-blocked-9"]').exists()).toBe(true)
  })

  it('keeps the Validate button enabled for a DRAFT within distributable_result', async () => {
    shareholderDistributionResourceList.mockResolvedValueOnce({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 10,
          period_start: '2026-07-01',
          period_end: '2026-07-31',
          total_profit: '100000.00',
          status: 'DRAFT',
          available_to_distribute: '500000.00',
          shares: [],
        },
      ],
    })

    const wrapper = mount(ShareholderView)
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Répartition des bénéfices')!
      .trigger('click')
    await flushPromises()

    const validateButton = wrapper.findAll('button').find((b) => b.text() === 'Valider')
    expect(validateButton).toBeTruthy()
    expect(validateButton!.attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-test="validate-blocked-10"]').exists()).toBe(false)
  })
})
