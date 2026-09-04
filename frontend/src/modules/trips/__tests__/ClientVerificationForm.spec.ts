import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ClientVerificationForm from '../ClientVerificationForm.vue'

const postClientVerification = vi.fn(async (_tripId: number, payload: Record<string, unknown>) => ({
  id: 1,
  trip: 9,
  loaded_quantity: '45000.00',
  received_quantity: payload.received_quantity,
  loss_quantity: '150.00',
  chargeable_loss_quantity: '50.00',
  tolerance_quantity: '100.00',
  control_date: '2026-08-18',
  controller: 1,
  controller_detail: null,
  method: 'MANUAL_GAUGE',
  document: null,
  notes: payload.notes ?? '',
  anomaly_confirmed_by: null,
  anomaly_confirmed_by_detail: null,
  anomaly_confirmed_at: null,
  verified_at: payload.verified_at,
  created_at: '',
  updated_at: '',
}))
vi.mock('../api', () => ({
  postClientVerification: (tripId: number, payload: Record<string, unknown>) =>
    postClientVerification(tripId, payload),
}))

const fetchLossTolerance = vi.fn(async () => ({
  tolerance_litres: '100.00',
  updated_by: null,
  updated_by_detail: null,
  updated_at: null,
}))
vi.mock('@/modules/settings/api', () => ({
  fetchLossTolerance: () => fetchLossTolerance(),
}))

describe('ClientVerificationForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('shows the loaded quantity read-only and computes company-absorbed vs transporter-chargeable loss client-side', async () => {
    const wrapper = mount(ClientVerificationForm, {
      props: { tripId: 1, quantityLoaded: '45000.00' },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('45 000')
    expect(wrapper.find('#loaded_quantity_display').exists()).toBe(true)

    await wrapper.find('[data-test="received-quantity"]').setValue('44850')
    await flushPromises()

    expect(wrapper.text()).toContain('100')
    expect(wrapper.text()).toContain('50')
  })

  it('submits the verification and emits the server response', async () => {
    const wrapper = mount(ClientVerificationForm, {
      props: { tripId: 1, quantityLoaded: '45000.00' },
    })
    await flushPromises()

    await wrapper.find('[data-test="received-quantity"]').setValue('44850')
    await wrapper.find('#verified_at').setValue('2026-08-18')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    const [, payload] = postClientVerification.mock.calls[0]!
    expect(Number(payload.received_quantity)).toBe(44850)
    expect(payload.verified_at).toBe('2026-08-18')
    expect(wrapper.emitted('verified')).toBeTruthy()
    const [emittedControl] = wrapper.emitted('verified')![0] as [Record<string, unknown>]
    expect(emittedControl.chargeable_loss_quantity).toBe('50.00')
  })

  it('blocks submission until a received quantity is entered', async () => {
    const wrapper = mount(ClientVerificationForm, {
      props: { tripId: 1, quantityLoaded: '45000.00' },
    })
    await flushPromises()

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(postClientVerification).not.toHaveBeenCalled()
  })

  it('surfaces the server error message on a rejected request', async () => {
    postClientVerification.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'Trip is not delivered yet.' } },
    })
    const wrapper = mount(ClientVerificationForm, {
      props: { tripId: 1, quantityLoaded: '45000.00' },
    })
    await flushPromises()

    await wrapper.find('[data-test="received-quantity"]').setValue('44850')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Trip is not delivered yet.')
  })
})
