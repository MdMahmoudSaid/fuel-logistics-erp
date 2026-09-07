import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ExpensesView from '../ExpensesView.vue'

const expenseList = vi.fn()
const expenseRemove = vi.fn()
const categoryList = vi.fn()
const fetchPayableDebts = vi.fn()
const cancelExpense = vi.fn()

vi.mock('../ExpenseForm.vue', () => ({
  default: {
    name: 'ExpenseForm',
    props: ['editingExpense'],
    emits: ['success', 'cancel'],
    template: '<form data-test="expense-form" @submit.prevent="$emit(\'success\', null)"></form>',
  },
}))

vi.mock('../api', () => ({
  expenseResource: {
    list: (...args: unknown[]) => expenseList(...args),
    remove: (...args: unknown[]) => expenseRemove(...args),
  },
  expenseCategoryResource: { list: (...args: unknown[]) => categoryList(...args) },
  fetchPayableDebts: (...args: unknown[]) => fetchPayableDebts(...args),
  cancelExpense: (...args: unknown[]) => cancelExpense(...args),
}))

function unpaidExpense(overrides: Record<string, unknown> = {}) {
  return {
    id: 44,
    category: 'rent',
    amount: '300000.00',
    calculation_method: 'MANUAL',
    date: '2026-09-02',
    status: 'UNPAID',
    paid_by_customer_directly: false,
    notes: 'Bureau',
    allocations_detail: [],
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:00:00Z',
    ...overrides,
  }
}

function mountView() {
  return mount(ExpensesView)
}

describe('ExpensesView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    expenseRemove.mockResolvedValue(undefined)
    cancelExpense.mockResolvedValue({})
    expenseList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
    categoryList.mockResolvedValue({
      count: 2,
      next: null,
      previous: null,
      results: [
        // Backend seed ships system categories with an English name - the
        // table must render the localised expenseCategory.* label instead.
        { id: 1, name: 'Customs', code: 'customs', is_system: true, is_active: true, display_order: 0 },
        { id: 2, name: 'Rent', code: 'rent', is_system: true, is_active: true, display_order: 9 },
      ],
    })
    fetchPayableDebts.mockResolvedValue([
      {
        id: 10,
        debt_type: 'customs',
        label: 'TRIP-1',
        total_amount: '100000.00',
        paid_amount: '25000.00',
        remaining_amount: '75000.00',
        status: 'UNPAID',
      },
    ])
  })

  it('renders the page title and empty state when there are no general expenses', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Dépenses générales')
    expect(wrapper.text()).toContain('Aucune dépense enregistrée sur cette période.')
  })

  it('loads only unallocated expenses and renders returned rows', async () => {
    expenseList.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 44,
          category: 'rent',
          amount: '300000.00',
          calculation_method: 'MANUAL',
          date: '2026-09-02',
          status: 'UNPAID',
          paid_by_customer_directly: false,
          notes: 'Bureau',
          allocations_detail: [],
          created_at: '2026-09-02T00:00:00Z',
          updated_at: '2026-09-02T00:00:00Z',
        },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    expect(expenseList).toHaveBeenCalledWith({ unallocated: 'true' })
    // Localised label, not the mock's English backend name ('Rent').
    expect(wrapper.text()).toContain('Loyer')
    expect(wrapper.text()).toContain('Bureau')
    expect(wrapper.text()).toContain('300 000 XOF')
  })

  it('opens the ExpenseForm modal from the new expense button', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-test="new-general-expense"]').trigger('click')

    expect(wrapper.findComponent({ name: 'UiModal' }).exists()).toBe(true)
    expect(wrapper.find('[data-test="expense-form"]').exists()).toBe(true)
  })

  it('renders read-only monitoring for all trip-fee debt buckets', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(fetchPayableDebts).toHaveBeenCalledTimes(6)
    for (const type of ['customs', 'transit', 'road_transit', 'border', 'loading', 'trip_other']) {
      expect(fetchPayableDebts).toHaveBeenCalledWith(type)
    }
    expect(wrapper.findAll('[data-test="debt-monitoring-card"]')).toHaveLength(6)
    expect(wrapper.text()).toContain('Douane')
    expect(wrapper.text()).toContain('Transit')
    expect(wrapper.text()).toContain('Transit routière')
    expect(wrapper.text()).toContain('Frontière')
    expect(wrapper.text()).toContain('Chargement')
    expect(wrapper.text()).toContain('Autres frais trajet')
    expect(wrapper.text()).toContain('75 000 XOF')
  })

  it('shows Modifier/Supprimer for an unpaid expense and Annuler for a paid one', async () => {
    expenseList.mockResolvedValue({
      count: 2,
      next: null,
      previous: null,
      results: [
        unpaidExpense({ id: 1, status: 'UNPAID' }),
        unpaidExpense({ id: 2, status: 'PAID', notes: 'Loyer payé' }),
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findAll('[data-test="edit-expense"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-test="delete-expense"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-test="cancel-expense"]')).toHaveLength(1)
  })

  it('opens the edit modal pre-filled when Modifier is clicked', async () => {
    const expense = unpaidExpense()
    expenseList.mockResolvedValue({ count: 1, next: null, previous: null, results: [expense] })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-test="edit-expense"]').trigger('click')

    const form = wrapper.findComponent({ name: 'ExpenseForm' })
    expect(form.exists()).toBe(true)
    expect(form.props('editingExpense')).toEqual(expense)
  })

  it('hard deletes an unpaid expense after confirmation, then reloads', async () => {
    window.confirm = vi.fn(() => true)
    expenseList.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [unpaidExpense()],
    })

    const wrapper = mountView()
    await flushPromises()
    expenseList.mockClear()

    await wrapper.find('[data-test="delete-expense"]').trigger('click')
    await flushPromises()

    expect(expenseRemove).toHaveBeenCalledWith(44)
    expect(expenseList).toHaveBeenCalledTimes(1)
  })

  it('does not delete when the confirmation is declined', async () => {
    window.confirm = vi.fn(() => false)
    expenseList.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [unpaidExpense()],
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-test="delete-expense"]').trigger('click')
    await flushPromises()

    expect(expenseRemove).not.toHaveBeenCalled()
  })

  it('cancels (not deletes) a paid expense, removing it from the debt calculation on reload', async () => {
    expenseList.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [unpaidExpense({ status: 'PAID' })],
    })

    const wrapper = mountView()
    await flushPromises()
    expenseList.mockClear()

    await wrapper.find('[data-test="cancel-expense"]').trigger('click')
    await flushPromises()

    expect(cancelExpense).toHaveBeenCalledWith(44)
    expect(expenseRemove).not.toHaveBeenCalled()
    expect(expenseList).toHaveBeenCalledTimes(1)
  })
})
