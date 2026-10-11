import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import TripCustomerRefusal from '../TripCustomerRefusal.vue'
import type { Trip } from '../types'

const confirmDialogMock = vi.fn(async () => true)
vi.mock('@/composables/useConfirmDialog', () => ({
  confirmDialog: () => confirmDialogMock(),
}))

const preview = vi.fn()
const refuse = vi.fn(async (..._args: unknown[]) => ({}))
vi.mock('../api', () => ({
  listAllCustomers: async () => [
    { id: 1, name: 'Client A', is_active: true },
    { id: 2, name: 'Client B', is_active: true },
    { id: 3, name: 'Client inactif', is_active: false },
  ],
  fetchCustomerRefusalPreview: (...args: unknown[]) => preview(...args),
  refuseTripCustomer: (...args: unknown[]) => refuse(...args),
}))

const trip = { id: 9, reference: 'TRIP-000009', status: 'ARRIVED_AT_CLIENT', client: 1 } as Trip

function side(id: number, name: string, before: string, after: string) {
  return { id, name, balance_before: before, balance_after: after }
}

async function mountModal(delivered: boolean) {
  const wrapper = mount(TripCustomerRefusal, {
    props: { trip, customerName: 'Client A', delivered },
  })
  await flushPromises()
  return wrapper
}

describe('TripCustomerRefusal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    preview.mockResolvedValue({
      trip_reference: 'TRIP-000009',
      action: 'RETURN_TO_STOCK',
      delivered: false,
      status_after: 'ARRIVED_AT_COMPANY_STOCK',
      invoice_number: null,
      grouped: false,
      quantity: null,
      current_unit_price: null,
      suggested_unit_price: null,
      unit_price: null,
      old_amount: '0.00',
      new_amount: '0.00',
      released_payments: '0.00',
      old_customer: side(1, 'Client A', '0.00', '0.00'),
      new_customer: null,
    })
  })

  it('before delivery: previews and confirms the return to stock', async () => {
    const wrapper = await mountModal(false)
    expect(preview).toHaveBeenCalledWith(9, expect.objectContaining({ action: 'RETURN_TO_STOCK' }))
    expect(wrapper.find('[data-test="refusal-preview"]').text()).toContain(
      'Arrivé au stock entreprise',
    )

    const submit = wrapper.find('[data-test="refusal-submit"]')
    expect(submit.attributes('disabled')).toBeDefined() // reason missing
    await wrapper.find('[data-test="refusal-reason"]').setValue('Le client ne veut plus')
    await submit.trigger('click')
    await flushPromises()

    expect(confirmDialogMock).toHaveBeenCalled()
    expect(refuse).toHaveBeenCalledWith(9, {
      action: 'RETURN_TO_STOCK',
      reason: 'Le client ne veut plus',
      customer: undefined,
      unit_selling_price: undefined,
    })
    expect(wrapper.emitted('done')).toBeTruthy()
  })

  it('after delivery: stock is disabled, the new customer and price are sent', async () => {
    preview.mockResolvedValue({
      trip_reference: 'TRIP-000009',
      action: 'CHANGE_CUSTOMER',
      delivered: true,
      status_after: 'COMPLETED',
      invoice_number: 'FAC-202610-0004',
      grouped: false,
      quantity: '45000.00',
      current_unit_price: '900.0000',
      suggested_unit_price: '950.0000',
      unit_price: '950.0000',
      old_amount: '40500000.00',
      new_amount: '42750000.00',
      released_payments: '10000000.00',
      old_customer: side(1, 'Client A', '40500000.00', '0.00'),
      new_customer: { ...side(2, 'Client B', '0.00', '42750000.00'), credit_applied: '0.00' },
    })
    const wrapper = await mountModal(true)
    expect(preview).not.toHaveBeenCalled() // waits for a customer
    const stockInput = wrapper.find('[data-test="refusal-choice-RETURN_TO_STOCK"] input')
    expect(stockInput.attributes('disabled')).toBeDefined()

    // The refusing customer and inactive ones are not offered.
    const picker = wrapper.find('[data-test="customer-refusal"] input[type="text"]')
    await picker.trigger('focus')
    await flushPromises()
    const items = wrapper.findAll('li').map((li) => li.text())
    expect(items).toContain('Client B')
    expect(items).not.toContain('Client A')
    expect(items).not.toContain('Client inactif')
    await wrapper
      .findAll('li')
      .find((li) => li.text() === 'Client B')!
      .trigger('mousedown')
    await flushPromises()

    expect(preview).toHaveBeenCalledWith(9, expect.objectContaining({ customer: 2 }))
    expect(
      (wrapper.find('[data-test="refusal-unit-price"]').element as HTMLInputElement).value,
    ).toBe('950.0000')
    expect(wrapper.find('[data-test="released-payments"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('FAC-202610-0004')

    await wrapper.find('[data-test="refusal-reason"]').setValue('Refus du produit')
    await wrapper.find('[data-test="refusal-submit"]').trigger('click')
    await flushPromises()
    expect(refuse).toHaveBeenCalledWith(9, {
      action: 'CHANGE_CUSTOMER',
      reason: 'Refus du produit',
      customer: 2,
      unit_selling_price: '950.0000',
    })
  })
})
