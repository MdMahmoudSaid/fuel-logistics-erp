<script setup lang="ts">
// docs/PHASE_5_PLAN.md Etape 10: customer selection, dynamic display of
// their unpaid invoices, and per-line allocation amounts - posted in one
// request to POST /api/customer-payments/ (backend/apps/finance/serializers.py
// CustomerPaymentSerializer consumes the nested `allocations` list via
// PaymentAllocationService.allocate_payment()).
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { customerPaymentResource, fetchCustomerLedger } from './api'
import type {
  CustomerBrief,
  CustomerLedgerInvoice,
  InvoiceAllocationInput,
  PaymentMethod,
} from './types'

const route = useRoute()
const router = useRouter()

const customerResource = createResourceApi<CustomerBrief>('/customers/')
const customers = ref<CustomerBrief[]>([])
const unpaidInvoices = ref<CustomerLedgerInvoice[]>([])
const loadingInvoices = ref(false)

const form = ref({
  customer: '',
  amount: '',
  payment_date: new Date().toISOString().slice(0, 10),
  method: 'CASH' as PaymentMethod,
  account_type: 'cash' as 'bank' | 'cash',
  bank_account: '',
  cash_account: '',
  reference: '',
  is_indirect: false,
})

const bankAccountResource = createResourceApi<{ id: number; name: string }>('/bank-accounts/')
const cashAccountResource = createResourceApi<{ id: number; name: string }>('/cash-accounts/')
const bankAccounts = ref<{ id: number; name: string }[]>([])
const cashAccounts = ref<{ id: number; name: string }[]>([])

interface AllocationLine {
  invoice: string
  amount: string
}
const lines = ref<AllocationLine[]>([{ invoice: '', amount: '' }])

const saving = ref(false)
const error = ref('')

async function loadInvoices() {
  unpaidInvoices.value = []
  if (!form.value.customer) return
  loadingInvoices.value = true
  try {
    const ledger = await fetchCustomerLedger(Number(form.value.customer))
    unpaidInvoices.value = ledger.invoices.filter(
      (inv) => Number(inv.outstanding) > 0 && inv.status !== 'CANCELLED' && inv.status !== 'DRAFT',
    )
  } finally {
    loadingInvoices.value = false
  }
}

watch(() => form.value.customer, loadInvoices)

onMounted(async () => {
  const [customerData, bankData, cashData] = await Promise.all([
    customerResource.list(),
    bankAccountResource.list(),
    cashAccountResource.list(),
  ])
  customers.value = customerData.results
  bankAccounts.value = bankData.results
  cashAccounts.value = cashData.results

  const preselected = route.query.customer
  if (preselected) {
    form.value.customer = String(preselected)
    await loadInvoices()
  }
})

function addLine() {
  lines.value.push({ invoice: '', amount: '' })
}

function removeLine(index: number) {
  lines.value.splice(index, 1)
}

const allocatedTotal = computed(() =>
  lines.value.reduce((sum, line) => sum + (Number(line.amount) || 0), 0),
)
const unallocatedRemainder = computed(() => (Number(form.value.amount) || 0) - allocatedTotal.value)

async function onSubmit() {
  saving.value = true
  error.value = ''
  try {
    const allocations: InvoiceAllocationInput[] = lines.value
      .filter((line) => line.amount)
      .map((line) => ({
        invoice: line.invoice ? Number(line.invoice) : null,
        amount: line.amount,
      }))

    const payload: Record<string, unknown> = {
      customer: Number(form.value.customer),
      amount: form.value.amount,
      payment_date: form.value.payment_date,
      method: form.value.method,
      reference: form.value.reference,
      is_indirect: form.value.is_indirect,
      allocations,
    }
    if (!form.value.is_indirect) {
      if (form.value.account_type === 'bank') {
        payload.bank_account = Number(form.value.bank_account)
      } else {
        payload.cash_account = Number(form.value.cash_account)
      }
    }

    const created = await customerPaymentResource.create(payload)
    router.push({ name: 'customer-ledger', params: { id: created.customer } })
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail || 'Could not record this payment — check the fields.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="max-w-3xl space-y-6">
    <h2 class="text-lg font-semibold text-slate-800">New Customer Payment</h2>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <form class="space-y-4 rounded border bg-white p-4" @submit.prevent="onSubmit">
      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="customer">Customer</label>
          <select
            id="customer"
            v-model="form.customer"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="" disabled>Select a customer</option>
            <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
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
          <label class="text-sm font-medium text-slate-600" for="payment_date">Payment date</label>
          <input
            id="payment_date"
            v-model="form.payment_date"
            type="date"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="method">Method</label>
          <select
            id="method"
            v-model="form.method"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="CASH">Cash</option>
            <option value="BANK_TRANSFER">Bank transfer</option>
            <option value="CHEQUE">Cheque</option>
            <option value="OTHER">Other</option>
          </select>
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="reference">Reference</label>
          <input
            id="reference"
            v-model="form.reference"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div class="flex items-center gap-2 pt-6">
          <input id="is_indirect" v-model="form.is_indirect" type="checkbox" />
          <label class="text-sm font-medium text-slate-600" for="is_indirect">
            Indirect payment (no treasury movement)
          </label>
        </div>
      </div>

      <div v-if="!form.is_indirect" class="grid grid-cols-2 gap-4 border-t pt-4">
        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="account_type">Account type</label>
          <select
            id="account_type"
            v-model="form.account_type"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="cash">Cash</option>
            <option value="bank">Bank</option>
          </select>
        </div>
        <div v-if="form.account_type === 'bank'" class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="bank_account">Bank account</label>
          <select
            id="bank_account"
            v-model="form.bank_account"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="" disabled>Select a bank account</option>
            <option v-for="a in bankAccounts" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>
        <div v-else class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="cash_account">Cash account</label>
          <select
            id="cash_account"
            v-model="form.cash_account"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="" disabled>Select a cash account</option>
            <option v-for="a in cashAccounts" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>
      </div>

      <div class="space-y-2 border-t pt-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-700">Allocate to invoices</h3>
          <button
            type="button"
            class="text-sm text-slate-500 hover:text-slate-800"
            @click="addLine"
          >
            + Add line
          </button>
        </div>
        <p v-if="loadingInvoices" class="text-sm text-slate-400">Loading unpaid invoices…</p>

        <div v-for="(line, index) in lines" :key="index" class="flex items-center gap-2">
          <select
            v-model="line.invoice"
            class="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">Unallocated credit</option>
            <option v-for="inv in unpaidInvoices" :key="inv.id" :value="inv.id">
              {{ inv.invoice_number }} — outstanding {{ Number(inv.outstanding).toLocaleString() }}
            </option>
          </select>
          <input
            v-model="line.amount"
            type="number"
            step="0.01"
            min="0"
            placeholder="Amount"
            class="w-40 rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            type="button"
            class="text-sm text-red-500 hover:text-red-700"
            @click="removeLine(index)"
          >
            Remove
          </button>
        </div>

        <p class="text-sm text-slate-500">
          Allocated: {{ allocatedTotal.toLocaleString() }} · Remaining unallocated:
          <span :class="unallocatedRemainder < 0 ? 'font-medium text-red-600' : ''">
            {{ unallocatedRemainder.toLocaleString() }}
          </span>
        </p>
      </div>

      <div class="flex justify-end">
        <button
          type="submit"
          :disabled="saving"
          class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {{ saving ? 'Saving…' : 'Record payment' }}
        </button>
      </div>
    </form>
  </div>
</template>
