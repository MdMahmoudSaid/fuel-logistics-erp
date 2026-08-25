import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import TransportPaymentForm from '../TransportPaymentForm.vue'

const createTransportPayment = vi.fn(async (payload: Record<string, unknown>) => ({
  id: 1,
  ...payload,
}))

vi.mock('../api', () => ({
  transportPaymentResource: {
    create: (payload: Record<string, unknown>) => createTransportPayment(payload),
  },
}))

const defaultProps = {
  tripId: 42,
  tripReference: 'TRIP-042',
  transporterId: 7,
  transporterName: 'Trans SA',
  quantityLoaded: '45000.00',
}

describe('TransportPaymentForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the trip transporter read-only (no dropdown) since a mismatch is rejected server-side', async () => {
    const wrapper = mount(TransportPaymentForm, { props: defaultProps })
    await flushPromises()

    expect(wrapper.text()).toContain('Trans SA')
    expect(wrapper.find('select').exists()).toBe(false)
  })

  it('computes and displays quantity x price = total live as the price is typed', async () => {
    const wrapper = mount(TransportPaymentForm, { props: defaultProps })
    await flushPromises()

    await wrapper.find('#unit_price_per_litre').setValue('60')

    expect(wrapper.text()).toContain((45000 * 60).toLocaleString())
  })

  it('submits calculation_method=PER_LITRE with the trip, transporter and unit price, never a client-computed base_amount', async () => {
    const wrapper = mount(TransportPaymentForm, { props: defaultProps })
    await flushPromises()

    await wrapper.find('#unit_price_per_litre').setValue('60')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(createTransportPayment).toHaveBeenCalledWith({
      trip: 42,
      transporter: 7,
      calculation_method: 'PER_LITRE',
      unit_price_per_litre: '60',
    })
    expect(wrapper.emitted('success')).toEqual([[]])
  })

  it('emits cancel without calling the API', async () => {
    const wrapper = mount(TransportPaymentForm, { props: defaultProps })
    await flushPromises()

    await wrapper.find('button[type=button]').trigger('click')

    expect(wrapper.emitted('cancel')).toEqual([[]])
    expect(createTransportPayment).not.toHaveBeenCalled()
  })
})
