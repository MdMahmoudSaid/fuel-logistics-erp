import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import LossEstimate from '../LossEstimate.vue'

const fetchLossTolerance = vi.fn(async () => ({ tolerance_litres: '100' }))
vi.mock('@/modules/settings/api', () => ({
  fetchLossTolerance: () => fetchLossTolerance(),
}))

async function mountEstimate(loaded: string, received: string) {
  const wrapper = mount(LossEstimate, {
    props: { quantityLoaded: loaded, receivedQuantity: received },
  })
  await flushPromises()
  return wrapper
}

describe('LossEstimate', () => {
  beforeEach(() => vi.clearAllMocks())

  it('splits the loss between the company (up to the tolerance) and the transporter (above it)', async () => {
    const wrapper = await mountEstimate('45000.00', '44800')

    expect(wrapper.text()).toContain("Perte absorbée par l'entreprise (est.)")
    expect(wrapper.text()).toContain('Perte facturable au transporteur (est.)')
    expect(wrapper.find('[data-test="company-absorbed"]').text()).toContain('100 L')
    expect(wrapper.find('[data-test="transporter-chargeable"]').text()).toContain('100 L')
  })

  it('shows zero loss when the full loaded quantity is received', async () => {
    const wrapper = await mountEstimate('45000.00', '45000')

    expect(wrapper.find('[data-test="company-absorbed"]').text()).toContain('0 L')
    expect(wrapper.find('[data-test="transporter-chargeable"]').text()).toContain('0 L')
  })

  it('uses the configured tolerance when it can be read', async () => {
    fetchLossTolerance.mockResolvedValueOnce({ tolerance_litres: '300' })
    const wrapper = await mountEstimate('45000.00', '44800')

    expect(wrapper.find('[data-test="company-absorbed"]').text()).toContain('200 L')
    expect(wrapper.find('[data-test="transporter-chargeable"]').text()).toContain('0 L')
  })

  it('is hidden until a quantity is typed', async () => {
    const wrapper = await mountEstimate('45000.00', '')

    expect(wrapper.find('[data-test="loss-estimate"]').exists()).toBe(false)
  })
})
