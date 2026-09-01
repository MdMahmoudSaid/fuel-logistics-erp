import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeliveryControlForm from '../DeliveryControlForm.vue'
import { useAuthStore } from '@/stores/auth'

const postDeliveryControl = vi.fn(async (_tripId: number, payload: Record<string, unknown>) => ({
  id: 1,
  trip: 9,
  loaded_quantity: '45000.00',
  received_quantity: payload.received_quantity,
  loss_quantity: '150.00',
  chargeable_loss_quantity: '50.00',
  tolerance_quantity: '100.00',
  control_date: payload.control_date,
  controller: 1,
  controller_detail: null,
  method: payload.method,
  document: null,
  notes: '',
  anomaly_confirmed_by: payload.anomaly_confirmed_by ?? null,
  anomaly_confirmed_by_detail: null,
  anomaly_confirmed_at: null,
  created_at: '',
  updated_at: '',
}))
const fetchSuggestedSellingPrice = vi.fn(async () => '850.0000')
const fetchTripCostBasis = vi.fn(async () => ({
  fuel_purchase_cost: '22500000.000000',
  transport_cost: '2925000.00',
  expenses_by_category: { transport: '450000.00', customs: '10125000.00' },
  total_expenses: '10575000.00',
  total_cost: '36000000.000000',
  quantity: '45000.00',
  unit_cost: '800.0000',
  unit_components_per_litre: {
    supplier: '500.0000',
    commission_transporter: '65.0000',
    road_transit: '10.0000',
    transit: '10.0000',
    border: '0.0000',
    customs: '225.0000',
    loading: '0.0000',
    other: '0.0000',
  },
}))
vi.mock('../api', () => ({
  postDeliveryControl: (tripId: number, payload: Record<string, unknown>) =>
    postDeliveryControl(tripId, payload),
  fetchSuggestedSellingPrice: () => fetchSuggestedSellingPrice(),
  fetchTripCostBasis: () => fetchTripCostBasis(),
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

function setAdminUser() {
  const auth = useAuthStore()
  auth.user = {
    id: 1,
    phone: '+22212345678',
    email: 'admin@example.com',
    full_name: 'Admin',
    role: 1,
    role_detail: {
      id: 1,
      name: 'Admin',
      permissions: { operations: ['view', 'create', 'edit', 'validate'] },
    },
  }
}

function setOpsUser() {
  const auth = useAuthStore()
  auth.user = {
    id: 2,
    phone: '+22212345678',
    email: 'ops@example.com',
    full_name: 'Ops',
    role: 2,
    role_detail: {
      id: 2,
      name: 'Operations',
      permissions: { operations: ['view', 'create', 'edit'] },
    },
  }
}

describe('DeliveryControlForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('shows the loaded quantity read-only and computes loss/chargeable loss live', async () => {
    setOpsUser()
    const wrapper = mount(DeliveryControlForm, { props: { tripId: 9, quantityLoaded: '45000.00' } })
    await flushPromises()

    expect(wrapper.text()).toContain('45 000')
    expect(wrapper.find('#loaded_quantity_display').exists()).toBe(true)

    await wrapper.find('#received_quantity').setValue('44850.00')
    await flushPromises()

    expect(wrapper.text()).toContain('150')
    expect(wrapper.text()).toContain('50')
  })

  it('warns and hides the confirm control from a non-authorized user when received exceeds loaded', async () => {
    setOpsUser()
    const wrapper = mount(DeliveryControlForm, { props: { tripId: 9, quantityLoaded: '45000.00' } })
    await flushPromises()

    await wrapper.find('#received_quantity').setValue('46000.00')
    await flushPromises()

    expect(wrapper.text()).toContain('anomalie')
    expect(wrapper.find('#anomaly_confirmed').exists()).toBe(false)

    await wrapper.find('#control_date').setValue('2026-08-18')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(postDeliveryControl).not.toHaveBeenCalled()
  })

  it('lets an authorized user confirm the anomaly and submits anomaly_confirmed_by', async () => {
    setAdminUser()
    const wrapper = mount(DeliveryControlForm, { props: { tripId: 9, quantityLoaded: '45000.00' } })
    await flushPromises()

    await wrapper.find('#received_quantity').setValue('46000.00')
    await wrapper.find('#control_date').setValue('2026-08-18')
    await flushPromises()

    expect(wrapper.find('#anomaly_confirmed').exists()).toBe(true)
    await wrapper.find('#anomaly_confirmed').setValue(true)

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(postDeliveryControl).toHaveBeenCalledWith(
      9,
      expect.objectContaining({ anomaly_confirmed_by: 1 }),
    )
    const [, payload] = postDeliveryControl.mock.calls[0]!
    expect(Number(payload.received_quantity)).toBe(46000)
  })

  it('emits confirmed with the server response on success', async () => {
    setOpsUser()
    const wrapper = mount(DeliveryControlForm, { props: { tripId: 9, quantityLoaded: '45000.00' } })
    await flushPromises()

    await wrapper.find('#received_quantity').setValue('44850.00')
    await wrapper.find('#control_date').setValue('2026-08-18')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.emitted('confirmed')).toBeTruthy()
    const [emittedControl] = wrapper.emitted('confirmed')![0] as [Record<string, unknown>]
    expect(emittedControl.chargeable_loss_quantity).toBe('50.00')
  })

  it('pre-fills the selling price from the suggestion and sends it with the payload', async () => {
    setOpsUser()
    const wrapper = mount(DeliveryControlForm, { props: { tripId: 9, quantityLoaded: '45000.00' } })
    await flushPromises()

    expect((wrapper.find('#unit_selling_price').element as HTMLInputElement).value).toBe('850.0000')

    await wrapper.find('#received_quantity').setValue('44850.00')
    await wrapper.find('#control_date').setValue('2026-08-18')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    const [, payload] = postDeliveryControl.mock.calls[0]!
    expect(payload.unit_selling_price).toBe('850.0000')
  })

  it('blocks submission when no price is suggested and none is entered', async () => {
    setOpsUser()
    fetchSuggestedSellingPrice.mockResolvedValueOnce(null as unknown as string)
    const wrapper = mount(DeliveryControlForm, { props: { tripId: 9, quantityLoaded: '45000.00' } })
    await flushPromises()

    await wrapper.find('#received_quantity').setValue('44850.00')
    await wrapper.find('#control_date').setValue('2026-08-18')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(postDeliveryControl).not.toHaveBeenCalled()
  })

  it('surfaces the server error message on a rejected request', async () => {
    setOpsUser()
    postDeliveryControl.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'No selling price configured.' } },
    })
    const wrapper = mount(DeliveryControlForm, { props: { tripId: 9, quantityLoaded: '45000.00' } })
    await flushPromises()

    await wrapper.find('#received_quantity').setValue('44850.00')
    await wrapper.find('#control_date').setValue('2026-08-18')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('No selling price configured.')
  })

  it('shows the cost price and live benefit once cost basis and selling price are known', async () => {
    setOpsUser()
    fetchSuggestedSellingPrice.mockResolvedValueOnce('850.0000')
    const wrapper = mount(DeliveryControlForm, { props: { tripId: 9, quantityLoaded: '45000.00' } })
    await flushPromises()

    expect(wrapper.text()).toContain('Prix fournisseur')
    expect(wrapper.text()).toContain('500')
    expect(wrapper.text()).toContain('Commission transporteur')
    expect(wrapper.text()).toContain('65')
    expect(wrapper.text()).toContain('Transit routière')
    expect(wrapper.text()).toContain('Transit')
    expect(wrapper.text()).toContain('10')
    expect(wrapper.text()).toContain('Douane')
    expect(wrapper.text()).toContain('225')
    expect(wrapper.text()).toContain('Prix de revient')
    expect(wrapper.text()).toContain('800')
    expect(wrapper.text()).toContain('Prix de vente saisi')
    expect(wrapper.text()).toContain('850')
    // Amounts are wrapped in bidi isolate marks (LRI/PDI) so they can't be
    // reordered in RTL locales; strip them before matching adjacent text.
    expect(wrapper.text().replace(/[⁦⁩]/g, '')).toContain('Bénéfice de 50')
    expect(wrapper.find('#loss_confirmed').exists()).toBe(false)
  })

  it('shows zero result when the selling price equals the cost price', async () => {
    setOpsUser()
    fetchSuggestedSellingPrice.mockResolvedValueOnce('800.0000')
    const wrapper = mount(DeliveryControlForm, { props: { tripId: 9, quantityLoaded: '45000.00' } })
    await flushPromises()

    expect(wrapper.text()).toContain('Résultat')
    expect(wrapper.text()).toContain('Zéro')
    expect(wrapper.find('#loss_confirmed').exists()).toBe(false)
  })

  it('warns and requires a confirmation checkbox when the selling price is below cost', async () => {
    setOpsUser()
    const wrapper = mount(DeliveryControlForm, { props: { tripId: 9, quantityLoaded: '45000.00' } })
    await flushPromises()

    await wrapper.find('#received_quantity').setValue('44850.00')
    await wrapper.find('#control_date').setValue('2026-08-18')
    await wrapper.find('#unit_selling_price').setValue('790.0000')
    await flushPromises()

    // Amounts are wrapped in bidi isolate marks (LRI/PDI) so they can't be
    // reordered in RTL locales; strip them before matching adjacent text.
    expect(wrapper.text().replace(/[⁦⁩]/g, '')).toContain('Perte de 10')
    expect(wrapper.text()).toContain('Attention : vente à perte')
    expect(wrapper.find('#loss_confirmed').exists()).toBe(true)

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(postDeliveryControl).not.toHaveBeenCalled()

    await wrapper.find('#loss_confirmed').setValue(true)
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(postDeliveryControl).toHaveBeenCalledWith(
      9,
      expect.objectContaining({ confirm_loss: true }),
    )
  })
})
