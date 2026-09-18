import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import TransportPaymentForm from '../TransportPaymentForm.vue'
import type { TransportPayment } from '../types'

const createTransportPayment = vi.fn(async (payload: Record<string, unknown>) => ({
  id: 1,
  ...payload,
}))
const updateTransportPayment = vi.fn(async (_id: number, _payload: Record<string, unknown>) => ({}))
const correctTransportPayment = vi.fn(async (_id: number, _payload: Record<string, unknown>) => ({}))

vi.mock('../api', () => ({
  transportPaymentResource: {
    update: (id: number, payload: Record<string, unknown>) => updateTransportPayment(id, payload),
    create: (payload: Record<string, unknown>) => createTransportPayment(payload),
  },
  correctTransportPayment: (id: number, payload: Record<string, unknown>) =>
    correctTransportPayment(id, payload),
}))

const defaultProps = {
  tripId: 42,
  tripReference: 'TRIP-042',
  transporterId: 7,
  transporterName: 'Trans SA',
  quantityLoaded: '45000.00',
}

describe('TransportPaymentForm', () => {
  it('edits a fixed commission without converting its calculation method', async () => {
    const wrapper = mount(TransportPaymentForm, {
      props: {
        ...defaultProps,
        payment: {
          id: 8,
          calculation_method: 'FIXED',
          unit_price_per_litre: null,
          base_amount: '1000',
        } as TransportPayment,
      },
    })
    await wrapper.find('#commission_amount').setValue('2000')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(updateTransportPayment).toHaveBeenCalledWith(8, { base_amount: '2000' })
  })

  it('keeps the editor open and displays validation errors when saving fails', async () => {
    updateTransportPayment.mockRejectedValueOnce({
      response: { data: { unit_price_per_litre: ['Prix invalide'] } },
    })
    const wrapper = mount(TransportPaymentForm, {
      props: {
        ...defaultProps,
        payment: {
          id: 8,
          calculation_method: 'PER_LITRE',
          unit_price_per_litre: '65',
          base_amount: '2925000',
        } as TransportPayment,
      },
    })
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.text()).toContain('Prix invalide')
    expect(wrapper.emitted('success')).toBeUndefined()
  })
  it('prefills and updates the existing commission instead of creating a second payment', async () => {
    const wrapper = mount(TransportPaymentForm, {
      props: {
        ...defaultProps,
        payment: {
          id: 8,
          calculation_method: 'PER_LITRE',
          unit_price_per_litre: '65.0000',
          base_amount: '2925000',
        } as TransportPayment,
      },
    })
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('65.0000')
    await wrapper.find('input').setValue('60')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(updateTransportPayment).toHaveBeenCalledWith(8, {
      calculation_method: 'PER_LITRE',
      unit_price_per_litre: '60',
    })
    expect(createTransportPayment).not.toHaveBeenCalled()
    expect(wrapper.emitted('success')).toEqual([[]])
  })
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

    expect(wrapper.text()).toContain('2 700 000 XOF')
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

  // Part 2 of the commission-actions bug fix (2026-09-17): mode="correct"
  // targets a settled commission via POST /correct/, never PATCH - see
  // TransportPaymentCorrectionService (backend) for why a trop-percu is
  // never clawed back in cash.
  describe('correction mode', () => {
    it('shows the correction notice and a required reason field', async () => {
      const wrapper = mount(TransportPaymentForm, {
        props: {
          ...defaultProps,
          mode: 'correct',
          payment: {
            id: 8,
            calculation_method: 'PER_LITRE',
            unit_price_per_litre: '65.0000',
            base_amount: '2925000',
          } as TransportPayment,
        },
      })
      expect(wrapper.find('#correction_reason').exists()).toBe(true)
      expect(
        (wrapper.find('#correction_reason').element as HTMLTextAreaElement).required,
      ).toBe(true)
    })

    it('posts the corrected per-litre rate and reason via correctTransportPayment, never PATCH', async () => {
      const wrapper = mount(TransportPaymentForm, {
        props: {
          ...defaultProps,
          mode: 'correct',
          payment: {
            id: 8,
            calculation_method: 'PER_LITRE',
            unit_price_per_litre: '65.0000',
            base_amount: '2925000',
          } as TransportPayment,
        },
      })
      await wrapper.find('#unit_price_per_litre').setValue('60')
      await wrapper.find('#correction_reason').setValue('Taux errone, le bon taux est 60 F/L')
      await wrapper.find('form').trigger('submit.prevent')
      await flushPromises()

      expect(correctTransportPayment).toHaveBeenCalledWith(8, {
        unit_price_per_litre: '60',
        reason: 'Taux errone, le bon taux est 60 F/L',
      })
      expect(updateTransportPayment).not.toHaveBeenCalled()
      expect(wrapper.emitted('success')).toEqual([[]])
    })

    it('posts a corrected fixed amount and reason', async () => {
      const wrapper = mount(TransportPaymentForm, {
        props: {
          ...defaultProps,
          mode: 'correct',
          payment: {
            id: 8,
            calculation_method: 'FIXED',
            unit_price_per_litre: null,
            base_amount: '100000',
          } as TransportPayment,
        },
      })
      await wrapper.find('#commission_amount').setValue('90000')
      await wrapper.find('#correction_reason').setValue('Trop-percu constate')
      await wrapper.find('form').trigger('submit.prevent')
      await flushPromises()

      expect(correctTransportPayment).toHaveBeenCalledWith(8, {
        base_amount: '90000',
        reason: 'Trop-percu constate',
      })
    })
  })
})
