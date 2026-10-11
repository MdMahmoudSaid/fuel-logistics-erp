import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ShareholderAdvancesPanel from '../ShareholderAdvancesPanel.vue'
import type { Shareholder, ShareholderLoan } from '../types'

const confirmDialogMock = vi.fn(async (_message: string) => true)
vi.mock('@/composables/useConfirmDialog', () => ({
  confirmDialog: (message: string) => confirmDialogMock(message),
}))

const loanList = vi.fn()
const loanCreate = vi.fn(async (_payload: Record<string, unknown>) => ({}))
const repay = vi.fn(async (_id: number, _payload: unknown) => ({}))
vi.mock('../api', () => ({
  shareholderLoanResource: {
    list: () => loanList(),
    create: (payload: Record<string, unknown>) => loanCreate(payload),
  },
  recordShareholderLoanRepayment: (id: number, payload: unknown) => repay(id, payload),
}))

function associate(id: number, name: string): Shareholder {
  return {
    id,
    name,
    participation_percent: '50.00',
    contribution: '0.00',
    total_contributed: '0.00',
    phone: '',
    notes: '',
    is_active: true,
    created_at: '',
    updated_at: '',
  } as Shareholder
}

function loan(overrides: Partial<ShareholderLoan>): ShareholderLoan {
  return {
    id: 1,
    source: 'COMPANY',
    borrower: 1,
    borrower_detail: { id: 1, name: 'Ahmed', participation_percent: '50', contribution: '0' },
    lender: null,
    lender_detail: null,
    bank_account: null,
    amount: '300000.00',
    date: '2026-10-01',
    status: 'OPEN',
    amount_repaid: '0.00',
    remaining_amount: '300000.00',
    amount_drawn: '300000.00',
    amount_cancelled: '0.00',
    undrawn_amount: '0.00',
    cash_outstanding: '300000.00',
    notes: '',
    repayments: [],
    created_at: '',
    updated_at: '',
    ...overrides,
  } as ShareholderLoan
}

function list(results: ShareholderLoan[]) {
  return { count: results.length, next: null, previous: null, results }
}

async function mountPanel() {
  const wrapper = mount(ShareholderAdvancesPanel, {
    props: {
      shareholders: [associate(1, 'Ahmed'), associate(2, 'Mohamed')],
      balances: {
        total: '1000000.00',
        shareholders: [
          { id: 1, name: 'Ahmed', available_balance: '800000.00' },
          { id: 2, name: 'Mohamed', available_balance: '200000.00' },
        ],
      },
      bankAccounts: [{ id: 3, name: 'Banque BOA', current_balance: '5000000.00' }],
      cashAccounts: [{ id: 7, name: 'Caisse principale', current_balance: '400000.00' }],
    },
  })
  await flushPromises()
  return wrapper
}

describe('ShareholderAdvancesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    loanList.mockResolvedValue(list([]))
  })

  it('grants a company advance without any treasury account and explains it', async () => {
    const wrapper = await mountPanel()
    expect(wrapper.find('[data-test="advance-account"]').exists()).toBe(false)
    await wrapper.find('[data-test="advance-borrower"]').setValue('1')
    await wrapper.find('[data-test="advance-amount"]').setValue('150000')

    const effect = wrapper.find('[data-test="advance-effect"]').text()
    expect(effect).toContain('Ahmed')
    expect(effect).toContain("l'argent sort seulement quand il fait le retrait")
    expect(effect).toContain('prochaine part de bénéfices')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirmDialogMock).toHaveBeenCalled()
    const payload = loanCreate.mock.calls[0]![0]
    expect(payload).toMatchObject({
      source: 'COMPANY',
      borrower: 1,
      lender: null,
      amount: '150000',
    })
    expect(payload).not.toHaveProperty('cash_account')
    expect(payload).not.toHaveProperty('bank_account')
    expect(wrapper.emitted('changed')).toBeTruthy()
  })

  it('records an associate advance without treasury and never offers the borrower as lender', async () => {
    const wrapper = await mountPanel()
    await wrapper.find('[data-test="advance-source-SHAREHOLDER"] input').setValue(true)
    await wrapper.find('[data-test="advance-borrower"]').setValue('2')

    const lenders = wrapper.findAll('[data-test="advance-lender"] option').map((o) => o.text())
    expect(lenders).toContain('Ahmed')
    expect(lenders).not.toContain('Mohamed')

    await wrapper.find('[data-test="advance-lender"]').setValue('1')
    await wrapper.find('[data-test="advance-amount"]').setValue('900000')
    expect(wrapper.find('[data-test="advance-blocking"]').exists()).toBe(true)

    await wrapper.find('[data-test="advance-amount"]').setValue('100000')
    expect(wrapper.find('[data-test="advance-effect"]').text()).toContain(
      'Aucun mouvement de banque ni de caisse',
    )
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(loanCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        source: 'SHAREHOLDER',
        borrower: 2,
        lender: 1,
      }),
    )
  })

  it('repays a company advance into a chosen treasury account', async () => {
    loanList.mockResolvedValue(list([loan({})]))
    const wrapper = await mountPanel()

    await wrapper.find('[data-test="advance-repay-1"]').trigger('click')
    expect((wrapper.find('[data-test="repay-amount"]').element as HTMLInputElement).value).toBe(
      '300000.00',
    )
    const submit = wrapper.find('[data-test="repay-submit"]')
    expect(submit.attributes('disabled')).toBeDefined() // account missing

    await wrapper.find('[data-test="repay-amount"]').setValue('100000')
    await wrapper.find('[data-test="repay-account"]').setValue('7')
    await wrapper.find('[data-test="advance-repay-form"]').trigger('submit')
    await flushPromises()

    expect(repay).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ amount: '100000.00', cash_account: 7, bank_account: null }),
    )
  })

  it('cancels a never-withdrawn advance without asking for any account', async () => {
    loanList.mockResolvedValue(
      list([loan({ amount_drawn: '0.00', undrawn_amount: '300000.00', cash_outstanding: '0.00' })]),
    )
    const wrapper = await mountPanel()

    await wrapper.find('[data-test="advance-repay-1"]').trigger('click')
    expect(wrapper.find('[data-test="repay-account"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="repay-split"]').text()).toContain('aucun mouvement de caisse')
    await wrapper.find('[data-test="advance-repay-form"]').trigger('submit')
    await flushPromises()

    expect(repay).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ amount: '300000.00', cash_account: null, bank_account: null }),
    )
  })

  it('asks for an account only for the part really withdrawn', async () => {
    loanList.mockResolvedValue(
      list([
        loan({
          amount_drawn: '100000.00',
          undrawn_amount: '200000.00',
          cash_outstanding: '100000.00',
        }),
      ]),
    )
    const wrapper = await mountPanel()

    await wrapper.find('[data-test="advance-repay-1"]').trigger('click')
    const split = wrapper.find('[data-test="repay-split"]').text()
    expect(split).toContain('200 000')
    expect(split).toContain('100 000')
    expect(wrapper.find('[data-test="repay-account"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="repay-submit"]').attributes('disabled')).toBeDefined()
  })

  it('lists open advances by default and shows the deduction history', async () => {
    loanList.mockResolvedValue(
      list([
        loan({
          id: 1,
          status: 'PARTIALLY_REPAID',
          amount_repaid: '100000.00',
          remaining_amount: '200000.00',
          repayments: [
            {
              id: 9,
              method: 'PROFIT_SHARE',
              amount: '100000.00',
              date: '2026-10-05',
              account_name: null,
              distribution_period: '2026-09-01 - 2026-09-30',
              notes: '',
            },
          ],
        }),
        loan({ id: 2, status: 'REPAID', amount_repaid: '300000.00', remaining_amount: '0.00' }),
        loan({
          id: 3,
          status: 'REPAID',
          amount_repaid: '300000.00',
          remaining_amount: '0.00',
          amount_drawn: '100000.00',
          undrawn_amount: '200000.00',
        }),
      ]),
    )
    const wrapper = await mountPanel()

    expect(wrapper.find('[data-test="advance-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="advance-2"]').exists()).toBe(false)
    // Deducted already, but 200 000 can still be withdrawn: still open.
    expect(wrapper.find('[data-test="advance-drawn-3"]').text()).toContain('200 000')

    await wrapper.find('[data-test="advance-history-1"]').trigger('click')
    expect(wrapper.find('[data-test="advance-1"]').text()).toContain(
      'Déduit de la répartition 2026-09-01 - 2026-09-30',
    )

    await wrapper.find('[data-test="advance-filter-all"]').trigger('click')
    expect(wrapper.find('[data-test="advance-2"]').exists()).toBe(true)
  })
})
