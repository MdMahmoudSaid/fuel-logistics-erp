import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import SupplierPaymentForm from '../SupplierPaymentForm.vue'

const createSupplierPayment = vi.fn(async (payload: Record<string, unknown>) => ({
  id: 1,
  ...payload,
}))
const listBankAccounts = vi.fn(async () => ({
  count: 2,
  next: null,
  previous: null,
  results: [
    { id: 5, name: 'Main BOA Account' },
    { id: 6, name: 'Secondary Account' },
  ],
}))

vi.mock('../api', () => ({
  supplierPaymentResource: {
    create: (payload: Record<string, unknown>) => createSupplierPayment(payload),
  },
}))

vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({ list: () => listBankAccounts() }),
}))

const defaultProps = {
  supplierId: 9,
  supplierName: 'Total Senegal',
  outstandingBalance: '15000000.00',
}

describe('SupplierPaymentForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the supplier outstanding balance before submission', async () => {
    const wrapper = mount(SupplierPaymentForm, { props: defaultProps })
    await flushPromises()

    expect(wrapper.text()).toContain('15 000 000 XOF')
  })

  it('only offers bank accounts to pick from - no cash account option at all', async () => {
    const wrapper = mount(SupplierPaymentForm, { props: defaultProps })
    await flushPromises()

    const options = wrapper.findAll('select option[value]:not([value=""])')
    expect(options).toHaveLength(2)
    expect(wrapper.text()).toContain('Main BOA Account')
    expect(wrapper.text()).not.toContain('cash_account')
  })

  it('forces the displayed method to "Virement bancaire" with no method selector', async () => {
    const wrapper = mount(SupplierPaymentForm, { props: defaultProps })
    await flushPromises()

    expect(wrapper.text()).toContain('Virement bancaire')
    // Only one <select> on the page - the bank account picker. No method
    // dropdown is exposed to the user; the payload always forces BANK_TRANSFER.
    expect(wrapper.findAll('select')).toHaveLength(1)
  })

  it('submits method=BANK_TRANSFER, is_advance=false and the picked bank account', async () => {
    const wrapper = mount(SupplierPaymentForm, { props: defaultProps })
    await flushPromises()

    await wrapper.find('#supplier_payment_amount').setValue('1000000')
    await wrapper.find('#supplier_payment_date').setValue('2026-08-25')
    await wrapper.find('#supplier_payment_bank_account').setValue('5')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(createSupplierPayment).toHaveBeenCalledWith({
      supplier: 9,
      amount: '1000000',
      payment_date: '2026-08-25',
      method: 'BANK_TRANSFER',
      bank_account: 5,
      is_advance: false,
    })
    expect(wrapper.emitted('success')).toEqual([[]])
  })

  it('emits cancel without calling the API', async () => {
    const wrapper = mount(SupplierPaymentForm, { props: defaultProps })
    await flushPromises()

    await wrapper.find('button[type=button]').trigger('click')

    expect(wrapper.emitted('cancel')).toEqual([[]])
    expect(createSupplierPayment).not.toHaveBeenCalled()
  })
})
