<script setup lang="ts">
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
  fetchAllocatableTypes,
  fetchCustomerLedger,
  recordIndirectExpense,
} from './api'
import { EXPENSE_CATEGORIES } from './types'
import Button from '@/components/ui/Button.vue'
import EntityAllocationPicker, { type AllocationDraft } from './EntityAllocationPicker.vue'
import { formatMoney, formatQuantity, formatUnitMoney } from '@/utils/currency'
import type {
  AllocatableKind,
  AllocatableTypeMap,
  CustomerBrief,
  CustomerLedgerInvoice,
  ExpenseAllocationInput,
  ExpenseCalculationMethod,
  ExpenseCategory,
} from './types'

// When opened from a trip's "Frais du trajet" tab (TripDetail.vue), this
// pre-seeds the first allocation line locked onto that trip - the amount is
// still editable, and further lines can still be added (that's how a
// monthly customs fee gets split across several trips: open the form once
// from any one of them, then add one line per additional trip).
const props = defineProps<{
  presetAllocation?: { kind: AllocatableKind; objectId: number; label: string }
  initialCategory?: ExpenseCategory
  initialCalculationMethod?: ExpenseCalculationMethod
  perLitreQuantity?: string
  title?: string
}>()
const emit = defineEmits<{ success: [customerId: number | null]; cancel: [] }>()
const { t } = useI18n()

const form = ref({
  category: props.initialCategory ?? ('other' as ExpenseCategory),
  amount: '',
  calculation_method: props.initialCalculationMethod ?? ('MANUAL' as ExpenseCalculationMethod),
  date: new Date().toISOString().slice(0, 10),
  notes: '',
})

function emptyDraft(): AllocationDraft {
  return { kind: '', objectId: null, label: '', allocatedAmount: '' }
}

const lines = ref<AllocationDraft[]>(
  props.presetAllocation ? [{ ...props.presetAllocation, allocatedAmount: '' }] : [],
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
const perLitreMode = computed(
  () => form.value.calculation_method === 'PER_LITRE' && Boolean(props.perLitreQuantity),
)
const amountTotal = computed(() => {
  if (!perLitreMode.value) return form.value.amount
  const quantity = Number(props.perLitreQuantity)
  const amount = Number(form.value.amount)
  if (!quantity || !amount) return form.value.amount
  return (quantity * amount).toFixed(2)
})

async function onSubmit() {
  saving.value = true
  error.value = ''
  try {
    if (paidByCustomerDirectly.value) {
      await recordIndirectExpense({
        customer: Number(indirectForm.value.customer),
        invoice: indirectForm.value.invoice ? Number(indirectForm.value.invoice) : null,
        category: form.value.category,
        amount: amountTotal.value,
        calculation_method: form.value.calculation_method,
        date: form.value.date,
        notes: form.value.notes,
      })
      emit('success', Number(indirectForm.value.customer))
      return
    }

    const allocations: ExpenseAllocationInput[] = lines.value
      .filter((line) => line.kind && line.objectId !== null && line.allocatedAmount)
      .map((line) => ({
        content_type: allocatableTypes.value[line.kind as AllocatableKind] ?? null,
        object_id: line.objectId,
        allocated_amount: perLitreMode.value ? amountTotal.value : line.allocatedAmount,
      }))

    await expenseResource.create({
      category: form.value.category,
      amount: amountTotal.value,
      calculation_method: form.value.calculation_method,
      date: form.value.date,
      notes: form.value.notes,
      allocations,
    })
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
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <form
      class="border-ligne space-y-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <div class="grid grid-cols-2 gap-4">
        <h2 v-if="title" class="font-display col-span-2 text-sm font-semibold uppercase">
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
            <option v-for="c in EXPENSE_CATEGORIES" :key="c.value" :value="c.value">
              {{ t(`expenseCategory.${c.value}`) }}
            </option>
          </select>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="calculation_method">{{
            t('finance.expense.calculationMethod')
          }}</label>
          <select
            id="calculation_method"
            v-model="form.calculation_method"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="FIXED">{{ t('expenseCalcMethod.FIXED') }}</option>
            <option value="PER_LITRE">{{ t('expenseCalcMethod.PER_LITRE') }}</option>
            <option value="PERCENTAGE">{{ t('expenseCalcMethod.PERCENTAGE') }}</option>
            <option value="PER_ORDER">{{ t('expenseCalcMethod.PER_ORDER') }}</option>
            <option value="PER_TRUCK">{{ t('expenseCalcMethod.PER_TRUCK') }}</option>
            <option value="MANUAL">{{ t('expenseCalcMethod.MANUAL') }}</option>
          </select>
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
        <div class="grid grid-cols-2 gap-4">
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
                {{ inv.invoice_number }} — outstanding
                {{ formatMoney(inv.outstanding) }}
              </option>
            </select>
          </div>
        </div>
      </template>

      <div v-else class="border-ligne space-y-2 border-t pt-4">
        <div
          v-if="perLitreMode"
          class="border-ligne flex items-center justify-between rounded-lg border bg-fond px-3.5 py-2.5 text-sm"
        >
          <span class="text-texte-2">{{ t('finance.expense.perLitreCalculation') }}</span>
          <span class="text-texte font-medium">
            {{ formatQuantity(perLitreQuantity ?? 0) }} × {{ formatUnitMoney(form.amount || 0) }} =
            {{ formatMoney(amountTotal || 0) }}
          </span>
        </div>
        <div class="flex items-center justify-between">
          <h2 class="font-display text-sm font-semibold uppercase">
            {{ t('finance.expense.allocationOptional') }}
          </h2>
          <button
            v-if="!perLitreMode"
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
      </div>

      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('cancel')">
          {{ t('common.cancel') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('finance.expense.saving') : t('finance.expense.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>
