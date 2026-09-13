import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ClientVerificationCorrectionForm from '../ClientVerificationCorrectionForm.vue'

const postClientVerificationCorrection = vi.fn(
  async (_tripId: number, payload: Record<string, unknown>) => ({
    id: 1,
    trip: 9,
    loaded_quantity: '45000.00',
    received_quantity: payload.received_quantity,
    loss_quantity: '100.00',
    chargeable_loss_quantity: '0.00',
    tolerance_quantity: '100.00',
    control_date: '2026-08-18',
    controller: 1,
    controller_detail: null,
    method: 'MANUAL_GAUGE',
    document: null,
    notes: '',
    anomaly_confirmed_by: null,
    anomaly_confirmed_by_detail: null,
    anomaly_confirmed_at: null,
    verified_at: '2026-08-18',
    verification_corrections: [],
    created_at: '',
    updated_at: '',
  }),
)
vi.mock('../api', () => ({
  postClientVerificationCorrection: (tripId: number, payload: Record<string, unknown>) =>
    postClientVerificationCorrection(tripId, payload),
}))

describe('ClientVerificationCorrectionForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the currently recorded quantity read-only', () => {
    const wrapper = mount(ClientVerificationCorrectionForm, {
      props: { tripId: 1, currentReceivedQuantity: '100.00' },
    })

    expect(wrapper.text()).toContain('100')
  })

  it('blocks submission until both the new quantity and a reason are provided', async () => {
    const wrapper = mount(ClientVerificationCorrectionForm, {
      props: { tripId: 1, currentReceivedQuantity: '100.00' },
    })

    await wrapper.find('[data-test="correction-received-quantity"]').setValue('44900')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(postClientVerificationCorrection).not.toHaveBeenCalled()

    await wrapper.find('[data-test="correction-reason"]').setValue('Perte saisie par erreur')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(postClientVerificationCorrection).toHaveBeenCalledTimes(1)
  })

  it('submits the correction and emits the server response', async () => {
    const wrapper = mount(ClientVerificationCorrectionForm, {
      props: { tripId: 1, currentReceivedQuantity: '100.00' },
    })

    await wrapper.find('[data-test="correction-received-quantity"]').setValue('44900')
    await wrapper.find('[data-test="correction-reason"]').setValue('Perte saisie par erreur')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    const [, payload] = postClientVerificationCorrection.mock.calls[0]!
    expect(Number(payload.received_quantity)).toBe(44900)
    expect(payload.reason).toBe('Perte saisie par erreur')
    expect(wrapper.emitted('corrected')).toBeTruthy()
  })

  it('emits cancel when the cancel button is clicked', async () => {
    const wrapper = mount(ClientVerificationCorrectionForm, {
      props: { tripId: 1, currentReceivedQuantity: '100.00' },
    })

    await wrapper.find('button[type="button"]').trigger('click')

    expect(wrapper.emitted('cancel')).toBeTruthy()
  })

  it('surfaces the server error message on a rejected request', async () => {
    postClientVerificationCorrection.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'No verification recorded yet.' } },
    })
    const wrapper = mount(ClientVerificationCorrectionForm, {
      props: { tripId: 1, currentReceivedQuantity: '100.00' },
    })

    await wrapper.find('[data-test="correction-received-quantity"]').setValue('44900')
    await wrapper.find('[data-test="correction-reason"]').setValue('Perte saisie par erreur')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('No verification recorded yet.')
  })
})
