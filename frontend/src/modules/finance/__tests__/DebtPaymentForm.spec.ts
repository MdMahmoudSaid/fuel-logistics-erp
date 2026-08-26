import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import DebtPaymentForm from '../DebtPaymentForm.vue'

const fetchPayableDebts = vi.fn()
const recordDebtPayment = vi.fn()

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    fetchPayableDebts: (...args: unknown[]) => fetchPayableDebts(...args),
    recordDebtPayment: (...args: unknown[]) => recordDebtPayment(...args),
  }
})

vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({
    list: vi.fn(async () => ({
      count: 1,
      next: null,
      previous: null,
      results: [{ id: 1, name: 'BIM', current_balance: '500000.00' }],
    })),
  }),
}))

describe('DebtPaymentForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchPayableDebts.mockResolvedValue([
      {
        id: 10,
        debt_type: 'supplier',
        label: 'Supplier 1',
        total_amount: '700000.00',
        paid_amount: '200000.00',
        remaining_amount: '500000.00',
        status: 'CONFIRMED',
        lines: [
          {
            id: 11,
            debt_type: 'supplier',
            label: 'SO-1 - Supplier 1',
            total_amount: '500000.00',
            paid_amount: '200000.00',
            remaining_amount: '300000.00',
            status: 'CONFIRMED',
          },
          {
            id: 12,
            debt_type: 'supplier',
            label: 'SO-2 - Supplier 1',
            total_amount: '200000.00',
            paid_amount: '0.00',
            remaining_amount: '200000.00',
            status: 'CONFIRMED',
          },
        ],
      },
    ])
    recordDebtPayment.mockResolvedValue({ transaction: { id: 1 } })
  })

  it('loads debts for the selected type and shows payment controls', async () => {
    const wrapper = mount(DebtPaymentForm)
    await flushPromises()

    expect(fetchPayableDebts).toHaveBeenCalledWith('supplier')
    const debtSelect = wrapper.find('select#debt')
    expect(debtSelect.text()).toContain('Supplier 1')
    expect(debtSelect.text()).not.toContain('SO-1 - Supplier 1')
    expect(wrapper.text()).toContain('SO-1 - Supplier 1')
    expect(wrapper.text()).toContain('SO-2 - Supplier 1')
    expect(wrapper.text()).toContain('700 000 XOF')
    expect(wrapper.text()).toContain('200 000 XOF')
    expect(wrapper.text()).toContain('500 000 XOF')
    expect(wrapper.text()).toContain('BIM')
  })

  it('rejects an amount greater than the remaining debt', async () => {
    const wrapper = mount(DebtPaymentForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('500001')
    await wrapper.find('form').trigger('submit')

    expect(recordDebtPayment).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Le montant dépasse le reste à payer.')
  })

  it('submits the note and a chosen attachment alongside the payment', async () => {
    const wrapper = mount(DebtPaymentForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('textarea').setValue('Virement confirme par SMS.')
    const file = new File(['%PDF-1.4'], 'recu.pdf', { type: 'application/pdf' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(recordDebtPayment).toHaveBeenCalledWith(
      expect.objectContaining({ note: 'Virement confirme par SMS.', attachment: file }),
    )
  })
})
