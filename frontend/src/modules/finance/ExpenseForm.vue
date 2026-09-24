<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// docs/PHASE_5_PLAN.md Etape 10: category, calculation method, allocation
// lines, and an "Paid directly by customer" switch that routes the
// submission through IndirectSettlementService instead of a plain Expense
// create (guide Section 1.6/8.9: never creates a TreasuryTransaction).
import { computed, ref, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import { translateApiError } from '@/i18n/apiErrors'
import {
  expenseResource,
  expenseCategoryResource,
  fetchAllocatableTypes,
  fetchCustomerLedger,
  createExpenseCategory,
  recordIndirectExpense,
} from './api'
import { EXPENSE_CATEGORIES } from './types'
import { useExpenseCategoryLabel } from './expenseCategoryLabel'
import Button from '@/components/ui/Button.vue'
import EntityAllocationPicker, { type AllocationDraft } from './EntityAllocationPicker.vue'
import { formatMoney, formatQuantity, formatUnitMoney } from '@/utils/currency'
import type {
  AllocatableKind,
  AllocatableTypeMap,
  CustomerBrief,
  CustomerLedgerInvoice,
  Expense,
  ExpenseAllocationInput,
  ExpenseCalculationMethod,
  ExpenseCategory,
  ExpenseCategoryOption,
} from './types'

// When opened from a trip's "Frais du trajet" tab (TripDetail.vue), this
// pre-seeds the first allocation line locked onto that trip - the amount is
// still editable, and further lines can still be added (that's how a
// monthly customs fee gets split across several trips: open the form once
// from any one of them, then add one line per additional trip).
const props = defineProps<{
  presetAllocation?: { kind: AllocatableKind; objectId: number; label: string }
  initialCategory?: ExpenseCategory
  cancelLabel?: string
  initialCalculationMethod?: ExpenseCalculationMethod
  perLitreQuantity?: string
  showTreasuryPayment?: boolean
  title?: string
  // Bug fix (2026-09-03 recette manuelle): "Frais du trajet" fees had no
  // way to be corrected once created, short of cancelling a paid one - an
  // UNPAID fee (the only status this is ever passed for) should be a
  // plain overwrite, same as any other draft-state record. When set, this
  // form pre-fills from the expense and PATCHes it instead of POSTing a
  // new one.
  editingExpense?: Expense | null
}>()
const emit = defineEmits<{ success: [customerId: number | null]; cancel: [] }>()
const { t } = useI18n()
const categoryLabel = useExpenseCategoryLabel()

interface ExpenseFormState {
  category: string
  amount: string
  calculation_method: ExpenseCalculationMethod
  date: string
  notes: string
}

interface AccountOption {
  id: number
  name: string
}

// Phase 5 (docs/superpowers/specs/2026-09-02-business-corrections-6-phases-
// design.md): a trip-allocated fee only ever uses "Par litre" or "Par
// camion" (backend ExpenseSerializer.validate() enforces the same rule) -
// "Manuel" isn't even a valid choice once presetAllocation targets a trip.
const isTripAllocation = computed(() => props.presetAllocation?.kind === 'trip')

// Bug fix (2026-09-03 recette manuelle): "Depenses generales" (opened by
// ExpensesView.vue with no presetAllocation at all) must be a strictly
// separate mode from a trip fee - it never shows trip system categories,
// never exposes "Methode de calcul" (always submitted as MANUAL), and
// never offers the "Repartition" allocation-lines UI (always submitted
// with zero allocations). Trip-fee mode stays exactly as before.
const isGeneralExpenseMode = computed(() => !props.presetAllocation)

const form = ref<ExpenseFormState>({
  category: props.editingExpense?.category ?? props.initialCategory ?? 'other',
  amount: props.editingExpense?.amount ?? '',
  calculation_method:
    props.editingExpense?.calculation_method ??
    props.initialCalculationMethod ??
    ((isTripAllocation.value ? 'PER_LITRE' : 'MANUAL') as ExpenseCalculationMethod),
  date: props.editingExpense?.date ?? new Date().toISOString().slice(0, 10),
  notes: props.editingExpense?.notes ?? '',
})

const categories = ref<ExpenseCategoryOption[]>([])
const creatingCategory = ref(false)
const newCategoryName = ref('')
const categoryError = ref('')
const savingCategory = ref(false)

// Bug fix (2026-09-03 recette manuelle): the trip-fee popup (opened with
// a presetAllocation of kind "trip") must only ever offer the system trip
// categories - a custom general category like "Internet" created on the
// Depenses generales page has no business appearing here, and used to show
// up because this list was never filtered. Matches the backend's own
// is_system=True set (apps/finance/migrations/0014, 0019). "transport" was
// dropped (migration 0019): a manual transport fee had no debt type to pay
// it - transporter commission is the only transport-cost channel.
const TRIP_SYSTEM_CATEGORY_CODES = ['customs', 'transit', 'road_transit', 'road', 'loading']

function fallbackCategories(): ExpenseCategoryOption[] {
  return EXPENSE_CATEGORIES.filter((category) => {
    const isTripSystemCategory = TRIP_SYSTEM_CATEGORY_CODES.includes(category.value)
    if (isTripAllocation.value) return isTripSystemCategory
    if (isGeneralExpenseMode.value) return !isTripSystemCategory
    return true
  }).map((category, index) => ({
    id: -(index + 1),
    name: t(`expenseCategory.${category.value}`),
    code: category.value,
    is_system: false,
    is_active: true,
    display_order: index,
  }))
}

async function loadCategories() {
  try {
    const params: Record<string, unknown> = { is_active: true }
    if (isTripAllocation.value) params.is_system = true
    else if (isGeneralExpenseMode.value) params.is_system = false
    categories.value = (await expenseCategoryResource.list(params)).results
  } catch {
    categories.value = fallbackCategories()
  }
  if (!categories.value.some((category) => category.code === form.value.category)) {
    form.value.category =
      categories.value.find((category) => category.code === 'other')?.code ??
      categories.value[0]?.code ??
      'other'
  }
}

async function onCreateCategory() {
  const name = newCategoryName.value.trim()
  if (!name) return
  savingCategory.value = true
  categoryError.value = ''
  try {
    const category = await createExpenseCategory({ name })
    categories.value = [...categories.value, category]
    form.value.category = category.code
    newCategoryName.value = ''
    creatingCategory.value = false
  } catch {
    categoryError.value = t('finance.expenseCategoryForm.createError')
  } finally {
    savingCategory.value = false
  }
}

function emptyDraft(): AllocationDraft {
  return { kind: '', objectId: null, label: '', allocatedAmount: '' }
}

const lines = ref<AllocationDraft[]>(
  props.presetAllocation
    ? [{ ...props.presetAllocation, allocatedAmount: props.editingExpense?.amount ?? '' }]
    : [],
)
const lockedFirstLine = Boolean(props.presetAllocation)

// Single-allocation mode: the top "Montant" field is the only amount the
// user needs to type, so it mirrors straight into the one pre-seeded line.
// The moment a second line is added, the split has to be entered by hand
// per line, so auto-sync switches off for good.
const autoSyncAmount = ref(lockedFirstLine)
watch(
  () => form.value.amount,
  (amount) => {
    if (autoSyncAmount.value && lines.value.length === 1) {
      lines.value[0] = { ...lines.value[0], allocatedAmount: amount }
    }
  },
)

function addLine() {
  autoSyncAmount.value = false
  lines.value.push(emptyDraft())
}
function removeLine(index: number) {
  lines.value.splice(index, 1)
}

const allocatableTypes = ref<AllocatableTypeMap>({})
onMounted(async () => {
  allocatableTypes.value = await fetchAllocatableTypes()
  await loadCategories()
})

const bankAccountResource = createResourceApi<AccountOption>('/bank-accounts/')
const cashAccountResource = createResourceApi<AccountOption>('/cash-accounts/')
const bankAccounts = ref<AccountOption[]>([])
const cashAccounts = ref<AccountOption[]>([])
const treasuryForm = ref({
  accountKind: 'bank' as 'bank' | 'cash',
  bankAccountId: '',
  cashAccountId: '',
})

onMounted(async () => {
  if (!props.showTreasuryPayment) return
  const [bankData, cashData] = await Promise.all([
    bankAccountResource.list(),
    cashAccountResource.list(),
  ])
  bankAccounts.value = bankData.results
  cashAccounts.value = cashData.results
  treasuryForm.value.bankAccountId = bankData.results[0]?.id ? String(bankData.results[0].id) : ''
  treasuryForm.value.cashAccountId = cashData.results[0]?.id ? String(cashData.results[0].id) : ''
})

// --- "Paid directly by customer" (indirect settlement) ---
const paidByCustomerDirectly = ref(false)
const customerResource = createResourceApi<CustomerBrief>('/customers/')
const customers = ref<CustomerBrief[]>([])
const customerInvoices = ref<CustomerLedgerInvoice[]>([])
const indirectForm = ref({ customer: '', invoice: '' })

onMounted(async () => {
  customers.value = (await customerResource.list()).results
})

async function onCustomerChange() {
  customerInvoices.value = []
  if (!indirectForm.value.customer) return
  const ledger = await fetchCustomerLedger(Number(indirectForm.value.customer))
  customerInvoices.value = ledger.invoices.filter(
    (inv) => Number(inv.outstanding) > 0 && inv.status !== 'CANCELLED' && inv.status !== 'DRAFT',
  )
}

const saving = ref(false)
const error = ref('')
// "Par litre" preview only - the backend (ExpenseSerializer._resolve_
// allocated_amount) is the authoritative source for a trip allocation's
// real total, computed the same way from the same inputs. `form.amount`
// itself always stays the XOF/L rate as typed - it is never overwritten
// with this computed total before submission.
const perLitreMode = computed(
  () => form.value.calculation_method === 'PER_LITRE' && Boolean(props.perLitreQuantity),
)
const perLitreTotal = computed(() => {
  const quantity = Number(props.perLitreQuantity)
  const amount = Number(form.value.amount)
  if (!quantity || !amount) return form.value.amount
  return (quantity * amount).toFixed(2)
})
const perTruckMode = computed(
  () => form.value.calculation_method === 'PER_TRUCK' && Boolean(props.perLitreQuantity),
)
const perTruckUnitCost = computed(() => {
  const quantity = Number(props.perLitreQuantity)
  const amount = Number(form.value.amount)
  if (!quantity || !amount) return '0'
  return (amount / quantity).toFixed(4)
})

async function onSubmit() {
  saving.value = true
  error.value = ''
  try {
    // Bug fix (2026-09-03 recette manuelle): general-expense mode must
    // never submit a trip calculation method or any allocation, no matter
    // what the (hidden) form/lines state happens to hold.
    const calculationMethod = isGeneralExpenseMode.value ? 'MANUAL' : form.value.calculation_method

    if (paidByCustomerDirectly.value) {
      await recordIndirectExpense({
        customer: Number(indirectForm.value.customer),
        invoice: indirectForm.value.invoice ? Number(indirectForm.value.invoice) : null,
        category: form.value.category,
        amount: form.value.amount,
        calculation_method: calculationMethod,
        date: form.value.date,
        notes: form.value.notes,
      })
      emit('success', Number(indirectForm.value.customer))
      return
    }

    const allocations: ExpenseAllocationInput[] = isGeneralExpenseMode.value
      ? []
      : lines.value
          .filter((line) => line.kind && line.objectId !== null && line.allocatedAmount)
          .map((line) => ({
            content_type: allocatableTypes.value[line.kind as AllocatableKind] ?? null,
            object_id: line.objectId,
            // For a trip allocation under PER_LITRE/PER_TRUCK the backend
            // recomputes this authoritatively from amount + the trip's
            // quantity_loaded (Phase 5) - this only satisfies the required-
            // field validator, it is never trusted as-is in that case.
            allocated_amount: line.allocatedAmount,
          }))

    const paymentFields = props.showTreasuryPayment
      ? {
          bank_account:
            treasuryForm.value.accountKind === 'bank' && treasuryForm.value.bankAccountId
              ? Number(treasuryForm.value.bankAccountId)
              : null,
          cash_account:
            treasuryForm.value.accountKind === 'cash' && treasuryForm.value.cashAccountId
              ? Number(treasuryForm.value.cashAccountId)
              : null,
        }
      : {}

    const payload = {
      category: form.value.category,
      amount: form.value.amount,
      calculation_method: calculationMethod,
      date: form.value.date,
      notes: form.value.notes,
      allocations,
      ...paymentFields,
    }
    if (props.editingExpense) {
      await expenseResource.update(props.editingExpense.id, payload)
    } else {
      await expenseResource.create(payload)
    }
    emit('success', null)
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = translateApiError(detail) || t('finance.expense.saveError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <AppAlert v-if="error" :message="error" />

    <form
      class="border-ligne space-y-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <h2 v-if="title" class="font-display md:col-span-2 text-sm font-semibold uppercase">
          {{ title }}
        </h2>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="category">{{
            t('finance.expense.category')
          }}</label>
          <select
            id="category"
            v-model="form.category"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option v-for="c in categories" :key="c.code" :value="c.code">
              {{ categoryLabel(c) }}
            </option>
          </select>
          <div v-if="!isTripAllocation" class="space-y-2">
            <button
              v-if="!creatingCategory"
              type="button"
              data-test="create-expense-category-toggle"
              class="text-bitume hover:text-orange text-sm font-medium"
              @click="creatingCategory = true"
            >
              {{ t('finance.expenseCategoryForm.createNew') }}
            </button>
            <div v-else class="border-ligne rounded-lg border bg-fond p-3">
              <label class="sr-only" for="new_expense_category_name">
                {{ t('finance.expenseCategoryForm.newCategoryName') }}
              </label>
              <div class="flex flex-wrap gap-2">
                <input
                  id="new_expense_category_name"
                  v-model="newCategoryName"
                  type="text"
                  class="border-ligne-forte h-10 min-w-0 flex-1 rounded-lg border bg-white px-3 text-sm focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                  :placeholder="t('finance.expenseCategoryForm.newCategoryName')"
                  @keydown.enter.prevent="onCreateCategory"
                />
                <Button
                  type="button"
                  variant="secondary"
                  :loading="savingCategory"
                  data-test="create-expense-category-submit"
                  @click="onCreateCategory"
                >
                  {{ t('finance.expenseCategoryForm.createButton') }}
                </Button>
                <Button type="button" variant="ghost" @click="creatingCategory = false">
                  {{ t('finance.expenseCategoryForm.cancelButton') }}
                </Button>
              </div>
              <AppAlert v-if="categoryError" :message="categoryError" />
            </div>
          </div>
        </div>

        <div v-if="!isGeneralExpenseMode" class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="calculation_method">{{
            t('finance.expense.calculationMethod')
          }}</label>
          <select
            id="calculation_method"
            v-model="form.calculation_method"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <template v-if="isTripAllocation">
              <option value="PER_LITRE">{{ t('expenseCalcMethod.PER_LITRE') }}</option>
              <option value="PER_TRUCK">{{ t('expenseCalcMethod.PER_TRUCK') }}</option>
            </template>
            <template v-else>
              <option value="FIXED">{{ t('expenseCalcMethod.FIXED') }}</option>
              <option value="PER_LITRE">{{ t('expenseCalcMethod.PER_LITRE') }}</option>
              <option value="PERCENTAGE">{{ t('expenseCalcMethod.PERCENTAGE') }}</option>
              <option value="PER_ORDER">{{ t('expenseCalcMethod.PER_ORDER') }}</option>
              <option value="PER_TRUCK">{{ t('expenseCalcMethod.PER_TRUCK') }}</option>
              <option value="MANUAL">{{ t('expenseCalcMethod.MANUAL') }}</option>
            </template>
          </select>
          <p v-if="isTripAllocation" class="text-texte-3 text-xs">
            {{ t('finance.expense.tripCalculationMethodHint') }}
          </p>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="amount">{{
            perLitreMode ? t('finance.expense.amountPerLitre') : t('finance.expense.amount')
          }}</label>
          <input
            id="amount"
            v-model="form.amount"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="date">{{
            t('finance.expense.date')
          }}</label>
          <input
            id="date"
            v-model="form.date"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="notes">{{
          t('finance.expense.notes')
        }}</label>
        <textarea
          id="notes"
          v-model="form.notes"
          rows="2"
          class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>

      <div class="border-ligne flex items-center gap-2 border-t pt-4">
        <input
          id="paid_by_customer"
          v-model="paidByCustomerDirectly"
          type="checkbox"
          class="border-ligne-forte accent-orange h-5 w-5 rounded"
        />
        <label class="text-texte-2 text-sm font-medium" for="paid_by_customer">
          {{ t('finance.expense.paidByCustomer') }}
        </label>
      </div>

      <template v-if="paidByCustomerDirectly">
        <p class="text-texte-2 text-sm">
          {{ t('finance.expense.paidByCustomerHint') }}
        </p>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="space-y-1.5">
            <label class="text-texte-2 text-sm font-medium" for="indirect_customer">{{
              t('finance.expense.customer')
            }}</label>
            <select
              id="indirect_customer"
              v-model="indirectForm.customer"
              required
              class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              @change="onCustomerChange"
            >
              <option value="" disabled>{{ t('finance.expense.selectCustomer') }}</option>
              <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </div>
          <div class="space-y-1.5">
            <label class="text-texte-2 text-sm font-medium" for="indirect_invoice">{{
              t('finance.expense.applyToInvoice')
            }}</label>
            <select
              id="indirect_invoice"
              v-model="indirectForm.invoice"
              class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              <option value="">{{ t('finance.expense.unallocatedCredit') }}</option>
              <option v-for="inv in customerInvoices" :key="inv.id" :value="inv.id">
                {{ inv.invoice_number }} — {{ t('finance.payment.invoiceOptionRemaining') }}
                {{ formatMoney(inv.outstanding) }}
              </option>
            </select>
          </div>
        </div>
      </template>

      <div v-else class="border-ligne space-y-2 border-t pt-4">
        <div
          v-if="showTreasuryPayment"
          class="border-ligne space-y-3 rounded-lg border bg-fond p-3"
        >
          <h2 class="font-display text-sm font-semibold uppercase">
            {{ t('finance.expense.treasuryPayment') }}
          </h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="space-y-1.5">
              <label class="text-texte-2 text-sm font-medium" for="treasury_account_kind">
                {{ t('finance.expense.accountType') }}
              </label>
              <select
                id="treasury_account_kind"
                v-model="treasuryForm.accountKind"
                class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                <option value="bank">{{ t('finance.expense.bankAccount') }}</option>
                <option value="cash">{{ t('finance.expense.cashAccount') }}</option>
              </select>
            </div>
            <div v-if="treasuryForm.accountKind === 'bank'" class="space-y-1.5">
              <label class="text-texte-2 text-sm font-medium" for="expense_bank_account">
                {{ t('finance.expense.bankAccount') }}
              </label>
              <select
                id="expense_bank_account"
                v-model="treasuryForm.bankAccountId"
                required
                class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                <option value="" disabled>{{ t('finance.expense.selectBankAccount') }}</option>
                <option v-for="account in bankAccounts" :key="account.id" :value="account.id">
                  {{ account.name }}
                </option>
              </select>
            </div>
            <div v-else class="space-y-1.5">
              <label class="text-texte-2 text-sm font-medium" for="expense_cash_account">
                {{ t('finance.expense.cashAccount') }}
              </label>
              <select
                id="expense_cash_account"
                v-model="treasuryForm.cashAccountId"
                required
                class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                <option value="" disabled>{{ t('finance.expense.selectCashAccount') }}</option>
                <option v-for="account in cashAccounts" :key="account.id" :value="account.id">
                  {{ account.name }}
                </option>
              </select>
            </div>
          </div>
        </div>

        <template v-if="!isGeneralExpenseMode">
          <div
            v-if="perLitreMode"
            class="border-ligne flex items-center justify-between rounded-lg border bg-fond px-3.5 py-2.5 text-sm"
          >
            <span class="text-texte-2">{{ t('finance.expense.perLitreCalculation') }}</span>
            <span class="text-texte font-medium">
              {{ formatQuantity(perLitreQuantity ?? 0) }} ×
              {{ formatUnitMoney(form.amount || 0) }} =
              {{ formatMoney(perLitreTotal || 0) }}
            </span>
          </div>
          <div
            v-if="perTruckMode"
            class="border-ligne flex items-center justify-between rounded-lg border bg-fond px-3.5 py-2.5 text-sm"
          >
            <span class="text-texte-2">{{ t('finance.expense.perTruckCalculation') }}</span>
            <span class="text-texte font-medium">
              {{ formatMoney(form.amount || 0) }} / {{ formatQuantity(perLitreQuantity ?? 0) }} =
              {{ perTruckUnitCost }} XOF/L
            </span>
          </div>
          <div class="flex items-center justify-between">
            <h2 class="font-display text-sm font-semibold uppercase">
              {{ t('finance.expense.allocationOptional') }}
            </h2>
            <button
              v-if="!perLitreMode && !perTruckMode"
              type="button"
              class="text-texte-2 hover:text-texte text-sm"
              @click="addLine"
            >
              {{ t('finance.expense.addLine') }}
            </button>
          </div>
          <p class="text-texte-3 text-xs">
            {{ t('finance.expense.allocationHint') }}
          </p>
          <div v-for="(line, index) in lines" :key="index" class="flex items-start gap-2">
            <EntityAllocationPicker
              :model-value="line"
              :locked="lockedFirstLine && index === 0"
              class="flex-1"
              @update:model-value="lines[index] = $event"
            />
            <button
              v-if="!(lockedFirstLine && index === 0)"
              type="button"
              class="text-critique mt-3 text-sm hover:brightness-90"
              @click="removeLine(index)"
            >
              {{ t('finance.expense.remove') }}
            </button>
          </div>
        </template>
      </div>

      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('cancel')">
          {{ cancelLabel ?? t('common.cancel') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('finance.expense.saving') : t('finance.expense.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>
