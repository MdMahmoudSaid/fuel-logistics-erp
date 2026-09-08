import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ExpenseForm from '../ExpenseForm.vue'

const createExpense = vi.fn(async (payload: Record<string, unknown>) => ({ id: 1, ...payload }))
const updateExpense = vi.fn(
  async (id: number, payload: Record<string, unknown>) => ({ id, ...payload }),
)
const fetchAllocatableTypes = vi.fn(async () => ({
  trip: 12,
  truck: 13,
  customer: 14,
  supplier: 15,
  transporter: 16,
}))
const ALL_TEST_CATEGORIES = [
  {
    id: 1,
    // The real backend seed stores system categories with an English name
    // (apps/finance/migrations/0014_expensecategory.py) - the UI must
    // translate through the expenseCategory.* i18n keys, not show this.
    name: 'Customs',
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
]
// Mirrors the real backend's filterset_fields = ["is_system", "is_active"]
// (apps/finance/views.py ExpenseCategoryViewSet) so tests can assert on
// what ExpenseForm actually requests, not just what it renders.
const listExpenseCategories = vi.fn(async (params: Record<string, unknown> = {}) => {
  const results = ALL_TEST_CATEGORIES.filter(
    (category) => params.is_system === undefined || category.is_system === params.is_system,
  )
  return { count: results.length, next: null, previous: null, results }
})
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
  expenseResource: {
    create: (payload: Record<string, unknown>) => createExpense(payload),
    update: (id: number, payload: Record<string, unknown>) => updateExpense(id, payload),
  },
  expenseCategoryResource: { list: (params?: Record<string, unknown>) => listExpenseCategories(params) },
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

  // Bug fix (2026-09-03 recette manuelle): "Depenses generales" (no
  // presetAllocation at all) must only ever offer general/custom
  // categories - a trip system category like "Douane" has no business
  // appearing here, mirroring the symmetric rule already enforced for
  // trip-fee mode below.
  it('loads only general categories from the API (never trip system ones) and can create a new one inline', async () => {
    const wrapper = mount(ExpenseForm)
    await flushPromises()

    expect(listExpenseCategories).toHaveBeenCalledWith(
      expect.objectContaining({ is_system: false }),
    )
    expect(wrapper.find('#category').text()).toContain('Internet')
    expect(wrapper.find('#category').text()).not.toContain('Douane')

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

  // Bug fix (2026-09-03 recette manuelle): a custom general category
  // (e.g. "Internet", created on the Depenses generales page) must never
  // appear in the trip-fee popup, and a user must not be able to create
  // one from there either.
  it('only offers system trip categories when allocated to a trip, and hides category creation', async () => {
    const wrapper = mount(ExpenseForm, {
      props: { presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' } },
    })
    await flushPromises()

    expect(listExpenseCategories).toHaveBeenCalledWith(
      expect.objectContaining({ is_system: true }),
    )
    expect(wrapper.find('#category').text()).toContain('Douane')
    expect(wrapper.find('#category').text()).not.toContain('Internet')
    expect(wrapper.find('[data-test="create-expense-category-toggle"]').exists()).toBe(false)
  })

  // A manual "Transport" trip fee reduced trip margin but no debt type
  // could pay it - the category is retired backend-side, and the offline
  // fallback list must not resurrect it either.
  it('never offers the retired "Transport" category in the trip-fee fallback', async () => {
    listExpenseCategories.mockRejectedValueOnce(new Error('offline'))
    const wrapper = mount(ExpenseForm, {
      props: { presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' } },
    })
    await flushPromises()

    const options = wrapper.find('#category').text()
    expect(options).toContain('Douane')
    expect(options).not.toContain('Transport')
  })

  // Recette 2026-09-07: the app is French but the category <select> showed
  // the seeded system categories' raw English backend name ("Customs",
  // "Transit", "Road transit"...). They must render through the localised
  // expenseCategory.* keys; a custom category keeps its user-typed name.
  it('shows localised system category labels, never the English backend name', async () => {
    const wrapper = mount(ExpenseForm, {
      props: { presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' } },
    })
    await flushPromises()

    const options = wrapper.find('#category').text()
    expect(options).toContain('Douane')
    expect(options).not.toContain('Customs')
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
    // Repartition (allocation lines) only renders for trip-fee mode now -
    // a general expense never offers this UI at all (see the dedicated
    // "hides Repartition optionnelle" test above).
    const wrapper = mount(ExpenseForm, {
      props: { presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' } },
    })
    await flushPromises()

    const addLineButton = wrapper.findAll('button').find((button) => button.text() === '+ Ajouter une ligne')
    await addLineButton!.trigger('click')
    expect(wrapper.text()).toContain('Retirer')

    const removeButton = wrapper.findAll('button').find((b) => b.text() === 'Retirer')
    await removeButton!.trigger('click')

    expect(wrapper.findAll('button').find((b) => b.text() === 'Retirer')).toBeUndefined()
  })

  // Phase 5 (docs/superpowers/specs/2026-09-02-business-corrections-6-
  // phases-design.md): a trip-allocated fee only ever uses Par litre / Par
  // camion.
  it('restricts calculation method to Par litre / Par camion when allocated to a trip', async () => {
    const wrapper = mount(ExpenseForm, {
      props: { presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' } },
    })
    await flushPromises()

    const options = wrapper.find('#calculation_method').findAll('option')
    expect(options.map((o) => o.element.value)).toEqual(['PER_LITRE', 'PER_TRUCK'])
  })

  // Bug fix (2026-09-03 recette manuelle): a general expense (Depenses
  // generales, no presetAllocation) is never a trip fee, so it must never
  // expose "Methode de calcul" at all - the submitted value is always
  // forced to MANUAL regardless of whatever the (hidden) field held.
  it('hides Methode de calcul entirely for a general (non-trip) expense and forces MANUAL on submit', async () => {
    const wrapper = mount(ExpenseForm)
    await flushPromises()

    expect(wrapper.find('#calculation_method').exists()).toBe(false)

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('#date').setValue('2026-08-25')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(createExpense).toHaveBeenCalledWith(
      expect.objectContaining({ calculation_method: 'MANUAL' }),
    )
  })

  // Bug fix (2026-09-03 recette manuelle): the "Repartition optionnelle"
  // allocation-lines UI is trip-fee-only machinery - a general expense has
  // no business splitting itself across trips/trucks/customers, so the
  // whole section (including "+ Ajouter une ligne") must not render.
  it('hides Repartition optionnelle entirely for a general (non-trip) expense', async () => {
    const wrapper = mount(ExpenseForm)
    await flushPromises()

    expect(wrapper.text()).not.toContain('Répartition')
    expect(
      wrapper.findAll('button').find((button) => button.text() === '+ Ajouter une ligne'),
    ).toBeUndefined()
  })

  it('submits the entered XOF/L rate as amount, not the computed total, for a Par litre trip fee', async () => {
    const wrapper = mount(ExpenseForm, {
      props: {
        presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' },
        perLitreQuantity: '45000.00',
      },
    })
    await flushPromises()

    expect((wrapper.find('#calculation_method').element as HTMLSelectElement).value).toBe(
      'PER_LITRE',
    )
    await wrapper.find('#amount').setValue('100')
    await wrapper.find('#date').setValue('2026-08-25')

    // Live preview shows the computed total without touching the amount field.
    expect(wrapper.text()).toContain('4 500 000 XOF')

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(createExpense).toHaveBeenCalledWith(
      expect.objectContaining({ calculation_method: 'PER_LITRE' }),
    )
    // The rate as typed, never the computed total (4 500 000).
    expect(Number(createExpense.mock.calls[0][0].amount)).toBe(100)
  })

  it('shows the derived cost-per-litre preview for a Par camion trip fee', async () => {
    const wrapper = mount(ExpenseForm, {
      props: {
        presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' },
        perLitreQuantity: '45000.00',
        initialCalculationMethod: 'PER_TRUCK',
      },
    })
    await flushPromises()

    await wrapper.find('#amount').setValue('10000')

    expect(wrapper.text()).toContain('0.2222')

    await wrapper.find('#date').setValue('2026-08-25')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(createExpense).toHaveBeenCalledWith(
      expect.objectContaining({ calculation_method: 'PER_TRUCK' }),
    )
    expect(Number(createExpense.mock.calls[0][0].amount)).toBe(10000)
  })

  // Bug fix (2026-09-03 recette manuelle): an UNPAID trip fee can now be
  // corrected in place instead of only being cancellable once paid.
  it('pre-fills from editingExpense and PATCHes instead of POSTing', async () => {
    const wrapper = mount(ExpenseForm, {
      props: {
        presetAllocation: { kind: 'trip', objectId: 42, label: 'TRIP-042' },
        editingExpense: {
          id: 99,
          category: 'customs',
          amount: '12000.00',
          calculation_method: 'PER_LITRE',
          date: '2026-08-25',
          status: 'UNPAID',
          paid_by_customer_directly: false,
          notes: 'note existante',
          allocations_detail: [],
          created_at: '',
          updated_at: '',
        },
      },
    })
    await flushPromises()

    expect((wrapper.find('#amount').element as HTMLInputElement).value).toBe('12000.00')
    expect((wrapper.find('#date').element as HTMLInputElement).value).toBe('2026-08-25')

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(updateExpense).toHaveBeenCalledWith(
      99,
      expect.objectContaining({ amount: '12000.00' }),
    )
    expect(createExpense).not.toHaveBeenCalled()
  })
})
