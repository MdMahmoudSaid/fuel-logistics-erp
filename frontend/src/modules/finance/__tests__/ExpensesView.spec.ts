import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ExpensesView from '../ExpensesView.vue'

const expenseList = vi.fn()
const categoryList = vi.fn()
const fetchPayableDebts = vi.fn()

vi.mock('../ExpenseForm.vue', () => ({
  default: {
    name: 'ExpenseForm',
    emits: ['success', 'cancel'],
    template: '<form data-test="expense-form" @submit.prevent="$emit(\'success\', null)"></form>',
  },
}))

vi.mock('../api', () => ({
  expenseResource: { list: (...args: unknown[]) => expenseList(...args) },
  expenseCategoryResource: { list: (...args: unknown[]) => categoryList(...args) },
  fetchPayableDebts: (...args: unknown[]) => fetchPayableDebts(...args),
}))

function mountView() {
  return mount(ExpensesView)
}

describe('ExpensesView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    expenseList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
    categoryList.mockResolvedValue({
      count: 2,
      next: null,
      previous: null,
      results: [
        { id: 1, name: 'Douane', code: 'customs', is_system: true, is_active: true, display_order: 0 },
        { id: 2, name: 'Loyer', code: 'rent', is_system: false, is_active: true, display_order: 9 },
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
})
