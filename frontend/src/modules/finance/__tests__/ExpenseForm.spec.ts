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
const listExpenseCategories = vi.fn(async () => ({
  count: 2,
  next: null,
  previous: null,
  results: [
    {
      id: 1,
      name: 'Douane',
      code: 'customs',
      is_system: true,
      is_active: true,
      display_order: 0,
    },
    {
      id: 2,
      name: 'Internet',
      code: 'internet',
      is_system: false,
      is_active: true,
      display_order: 10,
    },
  ],
}))
const createExpenseCategory = vi.fn(async (payload: Record<string, unknown>) => ({
  id: 3,
  name: payload.name,
  code: 'frais_wifi',
  is_system: false,
  is_active: true,
  display_order: 11,
}))
const listCustomers = vi.fn(async () => ({ count: 0, next: null, previous: null, results: [] }))
const listBanks = vi.fn(async () => ({
  count: 1,
  next: null,
  previous: null,
  results: [{ id: 7, name: 'Banque recette' }],
}))
const listCashAccounts = vi.fn(async () => ({
  count: 1,
  next: null,
  previous: null,
  results: [{ id: 9, name: 'Caisse bureau' }],
}))

vi.mock('../api', () => ({
  expenseResource: { create: (payload: Record<string, unknown>) => createExpense(payload) },
  expenseCategoryResource: { list: () => listExpenseCategories() },
  createExpenseCategory: (payload: Record<string, unknown>) => createExpenseCategory(payload),
  fetchAllocatableTypes: () => fetchAllocatableTypes(),
  fetchCustomerLedger: vi.fn(),
  recordIndirectExpense: vi.fn(),
}))

vi.mock('@/api/resource', () => ({
  createResourceApi: (path: string) => ({
    list: () => {
      if (path === '/bank-accounts/') return listBanks()
      if (path === '/cash-accounts/') return listCashAccounts()
      return listCustomers()
    },
  }),
}))

describe('ExpenseForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads categories from the API and can create a new one inline', async () => {
    const wrapper = mount(ExpenseForm)
    await flushPromises()

    expect(listExpenseCategories).toHaveBeenCalled()
    expect(wrapper.find('#category').text()).toContain('Douane')
    expect(wrapper.find('#category').text()).toContain('Internet')

    await wrapper.find('[data-test="create-expense-category-toggle"]').trigger('click')
    await wrapper.find('#new_expense_category_name').setValue('Frais WiFi')
    await wrapper.find('[data-test="create-expense-category-submit"]').trigger('click')
    await flushPromises()

    expect(createExpenseCategory).toHaveBeenCalledWith({ name: 'Frais WiFi' })
    expect((wrapper.find('#category').element as HTMLSelectElement).value).toBe('frais_wifi')
  })

  it('can submit a paid general expense with a bank account when enabled', async () => {
    const wrapper = mount(ExpenseForm, { props: { showTreasuryPayment: true } })
    await flushPromises()

    await wrapper.find('#amount').setValue('120000')
    await wrapper.find('#date').setValue('2026-09-02')
    await wrapper.find('#treasury_account_kind').setValue('bank')
    await wrapper.find('#expense_bank_account').setValue('7')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(createExpense).toHaveBeenCalledWith(
      expect.objectContaining({ bank_account: 7, cash_account: null, allocations: [] }),
    )
  })

  it('hides treasury payment controls by default for trip-fee usage', async () => {
    const wrapper = mount(ExpenseForm)
    await flushPromises()

    expect(wrapper.find('#treasury_account_kind').exists()).toBe(false)
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
    const addLineButton = wrapper.findAll('button').find((button) => button.text() === '+ Ajouter une ligne')
    await addLineButton!.trigger('click')

    await wrapper.find('input[type=number]').setValue('18000')

    expect((wrapper.findAll('input[type=number]')[1].element as HTMLInputElement).value).toBe(
      '12000',
    )
  })

  it('lets a manually added line be removed', async () => {
    const wrapper = mount(ExpenseForm)
    await flushPromises()

    const addLineButton = wrapper.findAll('button').find((button) => button.text() === '+ Ajouter une ligne')
    await addLineButton!.trigger('click')
    expect(wrapper.text()).toContain('Retirer')

    const removeButton = wrapper.findAll('button').find((b) => b.text() === 'Retirer')
    await removeButton!.trigger('click')

    expect(wrapper.findAll('button').find((b) => b.text() === 'Retirer')).toBeUndefined()
  })
})
