import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AssignCustomerForm from '../AssignCustomerForm.vue'

const customers = [
  { id: 1, name: 'Client A' },
  { id: 2, name: 'Client B' },
]

vi.mock('@/api/resource', () => ({
  createResourceApi: vi.fn(() => ({
    list: vi.fn(async () => ({ count: customers.length, next: null, previous: null, results: customers })),
  })),
}))

const assignTripCustomer = vi.fn(async (_tripId: number, _customerId: number) => ({}) as never)
vi.mock('../api', () => ({
  assignTripCustomer: (tripId: number, customerId: number) =>
    assignTripCustomer(tripId, customerId),
}))

async function mountForm() {
  const wrapper = mount(AssignCustomerForm, {
    props: { tripId: 9, tripReference: 'TRIP-000009' },
  })
  await flushPromises()
  return wrapper
}

async function pickCustomer(wrapper: Awaited<ReturnType<typeof mountForm>>, label: string) {
  const input = wrapper.find('input')
  await input.trigger('focus')
  await flushPromises()
  const item = wrapper.findAll('li').find((li) => li.text() === label)
  expect(item).toBeDefined()
  await item!.trigger('mousedown')
}

describe('AssignCustomerForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the trip reference and lists customers to pick from', async () => {
    const wrapper = await mountForm()
    expect(wrapper.text()).toContain('TRIP-000009')

    await wrapper.find('input').trigger('focus')
    await flushPromises()
    expect(wrapper.text()).toContain('Client A')
    expect(wrapper.text()).toContain('Client B')
  })

  it('disables the save button until a customer is picked', async () => {
    const wrapper = await mountForm()
    const saveButton = wrapper.findAll('button').find((b) => b.text() === 'Attribuer')
    expect(saveButton?.attributes('disabled')).toBeDefined()

    await pickCustomer(wrapper, 'Client A')
    expect(saveButton?.attributes('disabled')).toBeUndefined()
  })

  it('calls assignTripCustomer with the trip and picked customer, then emits success', async () => {
    const wrapper = await mountForm()
    await pickCustomer(wrapper, 'Client B')

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(assignTripCustomer).toHaveBeenCalledWith(9, 2)
    expect(wrapper.emitted('success')).toBeTruthy()
  })

  it('emits cancel when the cancel button is clicked', async () => {
    const wrapper = await mountForm()
    const cancelButton = wrapper.findAll('button').find((b) => b.text() === 'Annuler')
    await cancelButton!.trigger('click')

    expect(wrapper.emitted('cancel')).toBeTruthy()
  })

  it('shows a translated error message when the backend rejects the assignment', async () => {
    assignTripCustomer.mockRejectedValueOnce({
      response: { data: { detail: 'Le trajet TRIP-000009 a deja une vente enregistree.' } },
    })
    const wrapper = await mountForm()
    await pickCustomer(wrapper, 'Client A')

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.emitted('success')).toBeUndefined()
    expect(wrapper.find('.text-critique').exists()).toBe(true)
  })
})
