import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ConfirmQuantityForm from '../ConfirmQuantityForm.vue'

vi.mock('@/api/resource', () => ({
  createResourceApi: (url: string) => ({
    list: async () => ({
      count: 1,
      next: null,
      previous: null,
      results: url === '/bank-accounts/' ? [{ id: 1, name: 'BNP' }] : [{ id: 5, name: 'Caisse 1' }],
    }),
  }),
}))

const confirmReceivedQuantity = vi.fn(async (_id: number, _payload: unknown) => ({}) as never)
vi.mock('../api', () => ({
  confirmReceivedQuantity: (id: number, payload: unknown) => confirmReceivedQuantity(id, payload),
}))

async function mountForm(isWalkIn = false) {
  const wrapper = mount(ConfirmQuantityForm, {
    props: { tripId: 7, quantityLoaded: '45000.00', isWalkIn },
  })
  await flushPromises()
  return wrapper
}

describe('ConfirmQuantityForm', () => {
  beforeEach(() => vi.clearAllMocks())

  it('defaults to the loaded quantity and posts the entered quantity', async () => {
    const wrapper = await mountForm()
    const input = wrapper.find('[data-test="received-quantity"]')
    expect((input.element as HTMLInputElement).value).toBe('45000.00')

    await input.setValue('44000')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(confirmReceivedQuantity).toHaveBeenCalledWith(7, { received_quantity: '44000' })
    expect(wrapper.emitted('success')).toBeTruthy()
  })

  it('a walk-in needs an account before submitting, then sends payment_destination', async () => {
    const wrapper = await mountForm(true)
    const submit = wrapper.find('[data-test="submit"]')
    expect(submit.attributes('disabled')).toBeDefined()

    await wrapper.find('[data-test="pay-account"]').setValue('5')
    expect(submit.attributes('disabled')).toBeUndefined()

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(confirmReceivedQuantity).toHaveBeenCalledWith(7, {
      received_quantity: '45000.00',
      payment_destination: { destination: 'CASH', cash_account: 5 },
    })
  })

  it('when the backend asks for a loss confirmation, shows the checkbox and resubmits with confirm_loss', async () => {
    confirmReceivedQuantity.mockRejectedValueOnce({
      response: { status: 422, data: { detail: 'Vente a perte' } },
    })
    const wrapper = await mountForm()

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.emitted('success')).toBeUndefined()
    await wrapper.find('[data-test="loss-confirm"]').setValue(true)

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(confirmReceivedQuantity).toHaveBeenLastCalledWith(7, {
      received_quantity: '45000.00',
      confirm_loss: true,
    })
    expect(wrapper.emitted('success')).toBeTruthy()
  })
})
