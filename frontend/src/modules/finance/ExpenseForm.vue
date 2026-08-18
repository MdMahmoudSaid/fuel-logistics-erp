<script setup lang="ts">
// docs/PHASE_5_PLAN.md Etape 10: category, calculation method, allocation
// lines, and an "Paid directly by customer" switch that routes the
// submission through IndirectSettlementService instead of a plain Expense
// create (guide Section 1.6/8.9: never creates a TreasuryTransaction).
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { expenseResource, fetchCustomerLedger, recordIndirectExpense } from './api'
import { EXPENSE_CATEGORIES } from './types'
import type {
  CustomerBrief,
  CustomerLedgerInvoice,
  ExpenseAllocationInput,
  ExpenseCalculationMethod,
  ExpenseCategory,
} from './types'

const router = useRouter()

const form = ref({
  category: 'other' as ExpenseCategory,
  amount: '',
  calculation_method: 'MANUAL' as ExpenseCalculationMethod,
  date: new Date().toISOString().slice(0, 10),
  notes: '',
})

interface AllocationLine {
  content_type: string
  object_id: string
  allocated_amount: string
}
const lines = ref<AllocationLine[]>([])

function addLine() {
  lines.value.push({ content_type: '', object_id: '', allocated_amount: '' })
}
function removeLine(index: number) {
  lines.value.splice(index, 1)
}

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

async function onSubmit() {
  saving.value = true
  error.value = ''
  try {
    if (paidByCustomerDirectly.value) {
      await recordIndirectExpense({
        customer: Number(indirectForm.value.customer),
        invoice: indirectForm.value.invoice ? Number(indirectForm.value.invoice) : null,
        category: form.value.category,
        amount: form.value.amount,
        calculation_method: form.value.calculation_method,
        date: form.value.date,
        notes: form.value.notes,
      })
      router.push({ name: 'customer-ledger', params: { id: indirectForm.value.customer } })
      return
    }

    const allocations: ExpenseAllocationInput[] = lines.value
      .filter((line) => line.allocated_amount)
      .map((line) => ({
        content_type: line.content_type ? Number(line.content_type) : null,
        object_id: line.object_id ? Number(line.object_id) : null,
        allocated_amount: line.allocated_amount,
      }))

    await expenseResource.create({
      category: form.value.category,
      amount: form.value.amount,
      calculation_method: form.value.calculation_method,
      date: form.value.date,
      notes: form.value.notes,
      allocations,
    })
    router.push({ name: 'home' })
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail || 'Could not save this expense — check the fields.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <h2 class="text-lg font-semibold text-slate-800">New Expense</h2>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <form class="space-y-4 rounded border bg-white p-4" @submit.prevent="onSubmit">
      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="category">Category</label>
          <select
            id="category"
            v-model="form.category"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option v-for="c in EXPENSE_CATEGORIES" :key="c.value" :value="c.value">
              {{ c.label }}
            </option>
          </select>
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="calculation_method"
            >Calculation method</label
          >
          <select
            id="calculation_method"
            v-model="form.calculation_method"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="FIXED">Fixed</option>
            <option value="PER_LITRE">Per litre</option>
            <option value="PERCENTAGE">Percentage</option>
            <option value="PER_ORDER">Per order</option>
            <option value="PER_TRUCK">Per truck</option>
            <option value="MANUAL">Manual</option>
          </select>
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="amount">Amount</label>
          <input
            id="amount"
            v-model="form.amount"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="date">Date</label>
          <input
            id="date"
            v-model="form.date"
            type="date"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="notes">Notes</label>
        <textarea
          id="notes"
          v-model="form.notes"
          rows="2"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="flex items-center gap-2 border-t pt-4">
        <input id="paid_by_customer" v-model="paidByCustomerDirectly" type="checkbox" />
        <label class="text-sm font-medium text-slate-600" for="paid_by_customer">
          Paid directly by customer
        </label>
      </div>

      <template v-if="paidByCustomerDirectly">
        <p class="text-sm text-slate-500">
          This reduces the customer's receivable and marks the expense paid — no treasury movement
          is recorded.
        </p>
        <div class="grid grid-cols-2 gap-4">
          <div class="space-y-1">
            <label class="text-sm font-medium text-slate-600" for="indirect_customer"
              >Customer</label
            >
            <select
              id="indirect_customer"
              v-model="indirectForm.customer"
              required
              class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
              @change="onCustomerChange"
            >
              <option value="" disabled>Select a customer</option>
              <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </div>
          <div class="space-y-1">
            <label class="text-sm font-medium text-slate-600" for="indirect_invoice"
              >Apply to invoice (optional)</label
            >
            <select
              id="indirect_invoice"
              v-model="indirectForm.invoice"
              class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">Unallocated credit</option>
              <option v-for="inv in customerInvoices" :key="inv.id" :value="inv.id">
                {{ inv.invoice_number }} — outstanding
                {{ Number(inv.outstanding).toLocaleString() }}
              </option>
            </select>
          </div>
        </div>
      </template>

      <div v-else class="space-y-2 border-t pt-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-700">Allocation (optional)</h3>
          <button
            type="button"
            class="text-sm text-slate-500 hover:text-slate-800"
            @click="addLine"
          >
            + Add line
          </button>
        </div>
        <p class="text-xs text-slate-500">
          Split this expense across trips/trucks/customers via content type id + object id (guide
          Section 8.7: "a customs payment may affect several trips").
        </p>
        <div v-for="(line, index) in lines" :key="index" class="flex items-center gap-2">
          <input
            v-model="line.content_type"
            type="number"
            placeholder="Content type id"
            class="w-36 rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            v-model="line.object_id"
            type="number"
            placeholder="Object id"
            class="w-28 rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            v-model="line.allocated_amount"
            type="number"
            step="0.01"
            placeholder="Amount"
            class="w-32 rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            type="button"
            class="text-sm text-red-500 hover:text-red-700"
            @click="removeLine(index)"
          >
            Remove
          </button>
        </div>
      </div>

      <div class="flex justify-end">
        <button
          type="submit"
          :disabled="saving"
          class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {{ saving ? 'Saving…' : 'Save expense' }}
        </button>
      </div>
    </form>
  </div>
</template>
