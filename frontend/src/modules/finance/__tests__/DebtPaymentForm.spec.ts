import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import DebtPaymentForm from '../DebtPaymentForm.vue'

const fetchPayableDebts = vi.fn()
const recordDebtPayment = vi.fn()
const confirmDialogMock = vi.fn()

vi.mock('@/composables/useConfirmDialog', () => ({
  confirmDialog: (...args: unknown[]) => confirmDialogMock(...args),
}))

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

  it('can lock the debt type and preselect a debt from a detail page', async () => {
    fetchPayableDebts.mockResolvedValueOnce([
      {
        id: 10,
        debt_type: 'transporter',
        label: 'Trans A',
        total_amount: '700000.00',
        paid_amount: '0.00',
        remaining_amount: '700000.00',
        status: 'UNPAID',
      },
      {
        id: 22,
        debt_type: 'transporter',
        label: 'Trans B',
        total_amount: '400000.00',
        paid_amount: '0.00',
        remaining_amount: '400000.00',
        status: 'UNPAID',
      },
    ])

    const wrapper = mount(DebtPaymentForm, {
      props: {
        initialDebtType: 'transporter',
        initialDebtId: 22,
        lockDebtType: true,
      },
    })
    await flushPromises()

    expect(fetchPayableDebts).toHaveBeenCalledWith('transporter')
    const selects = wrapper.findAll('select')
    expect((selects[0].element as HTMLSelectElement).disabled).toBe(true)
    expect((selects[1].element as HTMLSelectElement).value).toBe('22')
    expect(wrapper.text()).toContain('Trans B')
  })

  it('locks strictly to the given debt and hides other entities from the list', async () => {
    fetchPayableDebts.mockResolvedValueOnce([
      {
        id: 10,
        debt_type: 'transporter',
        label: 'Transporteur Recette',
        total_amount: '700000.00',
        paid_amount: '0.00',
        remaining_amount: '700000.00',
        status: 'UNPAID',
      },
      {
        id: 22,
        debt_type: 'transporter',
        label: 'Transporteur Recette Net',
        total_amount: '400000.00',
        paid_amount: '0.00',
        remaining_amount: '400000.00',
        status: 'UNPAID',
      },
    ])

    const wrapper = mount(DebtPaymentForm, {
      props: {
        initialDebtType: 'transporter',
        initialDebtId: 10,
        lockDebtType: true,
        lockDebt: true,
      },
    })
    await flushPromises()

    const debtSelect = wrapper.find('select#debt')
    expect((debtSelect.element as HTMLSelectElement).value).toBe('10')
    expect(debtSelect.text()).toContain('Transporteur Recette')
    expect(debtSelect.text()).not.toContain('Transporteur Recette Net')
  })

  it('does not silently fall back to a different entity when the locked debt is missing from the payable list', async () => {
    fetchPayableDebts.mockResolvedValueOnce([
      {
        id: 22,
        debt_type: 'transporter',
        label: 'Transporteur Recette Net',
        total_amount: '400000.00',
        paid_amount: '0.00',
        remaining_amount: '400000.00',
        status: 'UNPAID',
      },
    ])

    const wrapper = mount(DebtPaymentForm, {
      props: {
        initialDebtType: 'transporter',
        initialDebtId: 10,
        lockDebtType: true,
        lockDebt: true,
      },
    })
    await flushPromises()

    const debtSelect = wrapper.find('select#debt')
    expect((debtSelect.element as HTMLSelectElement).value).not.toBe('22')
    expect(wrapper.text()).not.toContain('Transporteur Recette Net')

    await wrapper.find('#amount').setValue('1000')
    await wrapper.find('form').trigger('submit')
    expect(recordDebtPayment).not.toHaveBeenCalled()
  })

  function smallSupplierDebt(debtType = 'supplier') {
    fetchPayableDebts.mockResolvedValueOnce([
      {
        id: 10,
        debt_type: debtType,
        label: 'Supplier 1',
        total_amount: '300000.00',
        paid_amount: '0.00',
        remaining_amount: '300000.00',
        status: 'CONFIRMED',
      },
    ])
  }

  it('asks for confirmation before turning a supplier overpayment into an advance', async () => {
    smallSupplierDebt()
    confirmDialogMock.mockResolvedValueOnce(false)
    const wrapper = mount(DebtPaymentForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('400000')
    expect(wrapper.find('[data-test="surplus-hint"]').exists()).toBe(true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirmDialogMock).toHaveBeenCalledTimes(1)
    const message = confirmDialogMock.mock.calls[0][0] as string
    expect(message).toContain('Supplier 1')
    expect(message).toContain('300')
    expect(message).toContain('100')
    // Cancelled: nothing is recorded.
    expect(recordDebtPayment).not.toHaveBeenCalled()
  })

  it('records the overpayment with surplus_as_advance once confirmed', async () => {
    smallSupplierDebt()
    confirmDialogMock.mockResolvedValueOnce(true)
    const wrapper = mount(DebtPaymentForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('400000')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(recordDebtPayment).toHaveBeenCalledWith(
      expect.objectContaining({ amount: 400000, surplus_as_advance: true }),
    )
  })

  it('does not ask anything for a payment within the debt', async () => {
    const wrapper = mount(DebtPaymentForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirmDialogMock).not.toHaveBeenCalled()
    expect(recordDebtPayment).toHaveBeenCalledWith(
      expect.objectContaining({ surplus_as_advance: false }),
    )
  })

  it('still rejects an amount greater than the remaining debt for other debt types', async () => {
    fetchPayableDebts.mockResolvedValueOnce([]).mockResolvedValueOnce([
      {
        id: 0,
        debt_type: 'customs',
        label: 'Douane',
        total_amount: '300000.00',
        paid_amount: '0.00',
        remaining_amount: '300000.00',
        status: 'UNPAID',
      },
    ])
    const wrapper = mount(DebtPaymentForm)
    await flushPromises()
    await wrapper.findAll('select')[0].setValue('customs')
    await flushPromises()

    await wrapper.find('#amount').setValue('400000')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirmDialogMock).not.toHaveBeenCalled()
    expect(recordDebtPayment).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Le montant dépasse le reste à payer.')
  })

  it('submits the note and a chosen attachment alongside the payment', async () => {
    const wrapper = mount(DebtPaymentForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('textarea').setValue('Virement confirme par SMS.')
    const file = new File(['receipt'], 'recu.jpg', { type: 'image/jpeg' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(recordDebtPayment).toHaveBeenCalledWith(
      expect.objectContaining({ note: 'Virement confirme par SMS.', attachment: file }),
    )
  })

  it('offers road transit as a separate payable debt type and reloads debts when type changes', async () => {
    fetchPayableDebts
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          id: 0,
          debt_type: 'road_transit',
          label: 'Transit routière',
          total_amount: '450000.00',
          paid_amount: '0.00',
          remaining_amount: '450000.00',
          status: 'UNPAID',
          lines: [
            {
              id: 44,
              debt_type: 'road_transit',
              label: 'Transit routière 2026-08-18 - TRIP-009',
              total_amount: '450000.00',
              paid_amount: '0.00',
              remaining_amount: '450000.00',
              status: 'UNPAID',
            },
          ],
        },
      ])

    const wrapper = mount(DebtPaymentForm)
    await flushPromises()

    const typeSelect = wrapper.findAll('select')[0]
    expect(typeSelect.text()).toContain('Transit routière')
    await typeSelect.setValue('road_transit')
    await flushPromises()

    expect(fetchPayableDebts).toHaveBeenLastCalledWith('road_transit')
    expect((wrapper.find('select#debt').element as HTMLSelectElement).value).toBe('0')
    expect(wrapper.text()).toContain('Transit routière 2026-08-18 - TRIP-009')
  })

  it('shows a clear empty-debt message after switching to a type without open debts', async () => {
    fetchPayableDebts.mockResolvedValueOnce([
      {
        id: 10,
        debt_type: 'supplier',
        label: 'Supplier 1',
        total_amount: '700000.00',
        paid_amount: '200000.00',
        remaining_amount: '500000.00',
        status: 'CONFIRMED',
      },
    ])
    fetchPayableDebts.mockResolvedValueOnce([])

    const wrapper = mount(DebtPaymentForm)
    await flushPromises()

    await wrapper.findAll('select')[0].setValue('transporter')
    await flushPromises()

    expect((wrapper.find('select#debt').element as HTMLSelectElement).disabled).toBe(true)
    expect(wrapper.text()).toContain('Aucune dette ouverte pour ce type.')
  })

  // Task 14 (client modifications, 2026-09-04): proof upload is no longer
  // required client-side - the backend already accepts this flow without an
  // attachment.
  it('allows submitting a controlled outgoing payment without an attachment', async () => {
    const wrapper = mount(DebtPaymentForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(recordDebtPayment).toHaveBeenCalledWith(
      expect.objectContaining({ debt_id: 10, attachment: null }),
    )
  })
})
