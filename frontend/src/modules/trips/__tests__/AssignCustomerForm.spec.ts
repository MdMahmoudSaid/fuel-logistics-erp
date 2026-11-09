import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AssignCustomerForm from '../AssignCustomerForm.vue'

const customers = [
  { id: 1, name: 'Client A' },
  { id: 2, name: 'Client B' },
]
const lists: Record<string, unknown[]> = {
  '/customers/': customers,
  '/bank-accounts/': [{ id: 1, name: 'BNP' }],
  '/cash-accounts/': [{ id: 5, name: 'Caisse 1' }],
}

vi.mock('@/api/resource', () => ({
  createResourceApi: vi.fn((url: string) => ({
    list: vi.fn(async () => ({
      count: lists[url].length,
      next: null,
      previous: null,
      results: lists[url],
    })),
  })),
}))

const costBasis = {
  quantity: '45000.00',
  unit_cost: '725.8889',
  unit_components_per_litre: {
    supplier: '500',
    commission_transporter: '0',
    transit: '0.6667',
    road_transit: '0',
    border: '0',
    customs: '225',
    loading: '0.2222',
    other: '0',
  },
}
vi.mock('@/modules/settings/api', () => ({
  fetchLossTolerance: vi.fn(async () => ({ tolerance_litres: '100' })),
}))

const postDirectSale = vi.fn(async (_payload: unknown) => [] as never)
const costBasisById: Record<number, typeof costBasis> = {
  10: { ...costBasis, unit_cost: '560.0000', quantity: '45000.00' },
}
vi.mock('../api', () => ({
  fetchTripCostBasis: vi.fn(async (id: number) => costBasisById[id] ?? costBasis),
  postDirectSale: (payload: unknown) => postDirectSale(payload),
}))

type Wrapper = Awaited<ReturnType<typeof mountForm>>

async function mountForm(trips = [{ id: 9, reference: 'TRIP-000009' }]) {
  const wrapper = mount(AssignCustomerForm, { props: { trips } })
  await flushPromises()
  return wrapper
}

async function pickCustomer(wrapper: Wrapper, label: string) {
  await wrapper.find('input').trigger('focus')
  await flushPromises()
  const item = wrapper.findAll('li').find((li) => li.text() === label)
  expect(item).toBeDefined()
  await item!.trigger('mousedown')
  await flushPromises()
}

async function chooseWalkIn(wrapper: Wrapper) {
  await wrapper.find('[data-test="mode-walk-in"]').trigger('click')
  await flushPromises()
}

async function setPrice(wrapper: Wrapper, price: string) {
  await wrapper.find('[data-test="unit-price"]').setValue(price)
}

describe('AssignCustomerForm (direct sale)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('offers walk-in as a toggle above the customer field, not as a list entry', async () => {
    const wrapper = await mountForm()
    await wrapper.find('input').trigger('focus')
    await flushPromises()
    expect(wrapper.findAll('li').map((li) => li.text())).not.toContain('Client de passage')
    expect(wrapper.find('[data-test="mode-walk-in"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="mode-registered"]').exists()).toBe(true)
  })

  it('offers a walk-in option and then asks only for a name', async () => {
    const wrapper = await mountForm()
    await chooseWalkIn(wrapper)

    expect(wrapper.find('[data-test="walk-in-name"]').exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'UiSearchableSelect' }).exists()).toBe(false)
    expect(wrapper.text()).toContain('TRIP-000009')
  })

  it('shows one cost line, with the full breakdown behind the eye', async () => {
    const wrapper = await mountForm()
    await pickCustomer(wrapper, 'Client A')

    expect(wrapper.find('[data-test="cost-line"]').text()).toContain('725')
    expect(wrapper.text()).not.toContain('Douane')

    await wrapper.find('[data-test="cost-eye"]').trigger('click')
    expect(wrapper.text()).toContain('Douane')
  })

  it('shows profit above cost and the loss confirmation below cost', async () => {
    const wrapper = await mountForm()
    await pickCustomer(wrapper, 'Client A')

    await setPrice(wrapper, '900')
    expect(wrapper.text()).toContain('Bénéfice')
    expect(wrapper.find('[data-test="loss-confirm"]').exists()).toBe(false)

    await setPrice(wrapper, '700')
    expect(wrapper.find('[data-test="loss-confirm"]').exists()).toBe(true)
  })

  it('submits a registered customer without quantity (quantity later)', async () => {
    const wrapper = await mountForm()
    await pickCustomer(wrapper, 'Client B')
    await setPrice(wrapper, '900')

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(postDirectSale).toHaveBeenCalledWith({
      trips: [9],
      customer: 2,
      unit_selling_price: '900',
    })
    expect(wrapper.emitted('success')).toBeTruthy()
  })

  it('submits the received quantity keyed by trip id when entered now', async () => {
    const wrapper = await mountForm()
    await pickCustomer(wrapper, 'Client A')
    await setPrice(wrapper, '900')
    await wrapper.find('[data-test="quantity-now"]').setValue(true)

    const qty = wrapper.find('[data-test="qty-9"]')
    expect((qty.element as HTMLInputElement).value).toBe('45000')
    await qty.setValue('44000')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(postDirectSale).toHaveBeenCalledWith({
      trips: [9],
      customer: 1,
      unit_selling_price: '900',
      received_quantities: { '9': '44000' },
    })
  })

  it('walk-in with a quantity needs a payment account', async () => {
    const wrapper = await mountForm()
    await chooseWalkIn(wrapper)
    await wrapper.find('[data-test="walk-in-name"]').setValue('Moussa')
    await setPrice(wrapper, '900')
    await wrapper.find('[data-test="quantity-now"]').setValue(true)

    const submit = wrapper.find('[data-test="submit"]')
    expect(submit.attributes('disabled')).toBeDefined()

    await wrapper.find('[data-test="pay-account"]').setValue('5')
    expect(submit.attributes('disabled')).toBeUndefined()

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(postDirectSale).toHaveBeenCalledWith({
      trips: [9],
      walk_in_name: 'Moussa',
      unit_selling_price: '900',
      received_quantities: { '9': '45000' },
      payment_destination: { destination: 'CASH', cash_account: 5 },
    })
  })

  it('below cost: blocks submit until the loss is confirmed, then sends confirm_loss', async () => {
    const wrapper = await mountForm()
    await pickCustomer(wrapper, 'Client A')
    await setPrice(wrapper, '700')

    const submit = wrapper.find('[data-test="submit"]')
    expect(submit.attributes('disabled')).toBeDefined()
    await wrapper.find('[data-test="loss-confirm"]').setValue(true)
    expect(submit.attributes('disabled')).toBeUndefined()

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(postDirectSale).toHaveBeenCalledWith({
      trips: [9],
      customer: 1,
      unit_selling_price: '700',
      confirm_loss: true,
    })
  })

  it('emits cancel', async () => {
    const wrapper = await mountForm()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Annuler')!
      .trigger('click')
    expect(wrapper.emitted('cancel')).toBeTruthy()
  })

  it('shows an error and stays open when the backend refuses', async () => {
    postDirectSale.mockRejectedValueOnce({
      response: { data: { detail: 'Le trajet TRIP-000009 a deja une vente enregistree.' } },
    })
    const wrapper = await mountForm()
    await pickCustomer(wrapper, 'Client A')
    await setPrice(wrapper, '900')

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.emitted('success')).toBeUndefined()
    expect(wrapper.find('.text-critique').exists()).toBe(true)
  })

  it('flags a loss when any single trip is below cost, even if the weighted average is a profit', async () => {
    const wrapper = await mountForm([
      { id: 9, reference: 'TRIP-000009' }, // cost 725.8889
      { id: 10, reference: 'TRIP-000010' }, // cost 560
    ])
    await pickCustomer(wrapper, 'Client A')
    // 700 is above trip 10's cost (560) and above the average (643), but below trip 9's cost.
    await setPrice(wrapper, '700')

    expect(wrapper.find('[data-test="loss-confirm"]').exists()).toBe(true)
  })

  it('when the backend answers 422 it shows the loss confirmation and resends with confirm_loss', async () => {
    postDirectSale.mockRejectedValueOnce({
      response: { status: 422, data: { detail: 'Vente a perte' } },
    })
    const wrapper = await mountForm()
    await pickCustomer(wrapper, 'Client A')
    await setPrice(wrapper, '900')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.emitted('success')).toBeUndefined()
    await wrapper.find('[data-test="loss-confirm"]').setValue(true)
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(postDirectSale).toHaveBeenLastCalledWith({
      trips: [9],
      customer: 1,
      unit_selling_price: '900',
      confirm_loss: true,
    })
    expect(wrapper.emitted('success')).toBeTruthy()
  })

  it('takes whole litres only and shows the loss estimate under each trip quantity', async () => {
    const wrapper = await mountForm()
    await pickCustomer(wrapper, 'Client A')
    await setPrice(wrapper, '900')
    await wrapper.find('[data-test="quantity-now"]').setValue(true)

    const qty = wrapper.find('[data-test="qty-9"]')
    expect(qty.attributes('step')).toBe('1')
    await qty.setValue('44800')
    await flushPromises()
    expect(wrapper.find('[data-test="company-absorbed"]').text()).toContain('100 L')
    expect(wrapper.find('[data-test="transporter-chargeable"]').text()).toContain('100 L')

    await qty.setValue('44800.5')
    expect(wrapper.find('[data-test="submit"]').attributes('disabled')).toBeDefined()
  })
})
