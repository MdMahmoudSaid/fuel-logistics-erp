import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ExpenseForm from '../ExpenseForm.vue'

const createExpense = vi.fn(async (payload: Record<string, unknown>) => ({ id: 1, ...payload }))
const fetchAllocatableTypes = vi.fn(async () => ({
  trip: 12,
  truck: 13,
  customer: 14,
  supplier: 15,
  transporter: 16,
}))
const listCustomers = vi.fn(async () => ({ count: 0, next: null, previous: null, results: [] }))

vi.mock('../api', () => ({
  expenseResource: { create: (payload: Record<string, unknown>) => createExpense(payload) },
  fetchAllocatableTypes: () => fetchAllocatableTypes(),
  fetchCustomerLedger: vi.fn(),
  recordIndirectExpense: vi.fn(),
}))

vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({ list: () => listCustomers() }),
}))

describe('ExpenseForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('submits a plain expense with no allocation lines by default', async () => {
    const wrapper = mount(ExpenseForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('#date').setValue('2026-08-25')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(createExpense).toHaveBeenCalledWith(expect.objectContaining({ allocations: [] }))
    expect(Number(createExpense.mock.calls[0][0].amount)).toBe(100000)
    expect(wrapper.emitted('success')).toEqual([[null]])
  })

  it('pre-seeds a locked trip allocation line when presetAllocation is given, and resolves its content_type on submit', async () => {
    const wrapper = mount(ExpenseForm, {
      props: { presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('TRIP-042')
    // The preset line has no "remove" button.
    expect(wrapper.findAll('button').find((b) => b.text() === 'Retirer')).toBeUndefined()

    // The first type=number input is the top-level "amount" field; the
    // second is the (locked) allocation line's own amount input.
    const numberInputs = wrapper.findAll('input[type=number]')
    await numberInputs[0].setValue('75000')
    await numberInputs[1].setValue('75000')
    await wrapper.find('#date').setValue('2026-08-25')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(createExpense).toHaveBeenCalledWith(
      expect.objectContaining({
        allocations: [{ content_type: 12, object_id: 42, allocated_amount: '75000' }],
      }),
    )
  })

  it('auto-syncs the top amount into the single preset line without touching it directly', async () => {
    const wrapper = mount(ExpenseForm, {
      props: { presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' } },
    })
    await flushPromises()

    const numberInputs = wrapper.findAll('input[type=number]')
    await numberInputs[0].setValue('12000')

    expect((wrapper.findAll('input[type=number]')[1].element as HTMLInputElement).value).toBe(
      '12000',
    )

    await numberInputs[0].setValue('18000')
    expect((wrapper.findAll('input[type=number]')[1].element as HTMLInputElement).value).toBe(
      '18000',
    )
  })

  it('stops auto-syncing once a second allocation line is added', async () => {
    const wrapper = mount(ExpenseForm, {
      props: { presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' } },
    })
    await flushPromises()

    await wrapper.find('input[type=number]').setValue('12000')
    await wrapper.find('button:not([type=submit])').trigger('click') // "+ Ajouter une ligne"

    await wrapper.find('input[type=number]').setValue('18000')

    expect((wrapper.findAll('input[type=number]')[1].element as HTMLInputElement).value).toBe(
      '12000',
    )
  })

  it('lets a manually added line be removed', async () => {
    const wrapper = mount(ExpenseForm)
    await flushPromises()

    await wrapper.find('button:not([type=submit])').trigger('click') // "+ Ajouter une ligne" is the first non-submit button
    expect(wrapper.text()).toContain('Retirer')

    const removeButton = wrapper.findAll('button').find((b) => b.text() === 'Retirer')
    await removeButton!.trigger('click')

    expect(wrapper.findAll('button').find((b) => b.text() === 'Retirer')).toBeUndefined()
  })
})
