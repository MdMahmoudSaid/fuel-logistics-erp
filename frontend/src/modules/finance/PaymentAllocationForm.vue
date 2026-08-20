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
import Button from '@/components/ui/Button.vue'

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
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">New Customer Payment</h1>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <form
      class="border-ligne space-y-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="customer">Customer</label>
          <select
            id="customer"
            v-model="form.customer"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>Select a customer</option>
            <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="amount">Amount</label>
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
          <label class="text-texte-2 text-sm font-medium" for="payment_date">Payment date</label>
          <input
            id="payment_date"
            v-model="form.payment_date"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="method">Method</label>
          <select
            id="method"
            v-model="form.method"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="CASH">Cash</option>
            <option value="BANK_TRANSFER">Bank transfer</option>
            <option value="CHEQUE">Cheque</option>
            <option value="OTHER">Other</option>
          </select>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="reference">Reference</label>
          <input
            id="reference"
            v-model="form.reference"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>

        <div class="flex items-center gap-2 pt-6">
          <input
            id="is_indirect"
            v-model="form.is_indirect"
            type="checkbox"
            class="border-ligne-forte accent-orange h-5 w-5 rounded"
          />
          <label class="text-texte-2 text-sm font-medium" for="is_indirect">
            Indirect payment (no treasury movement)
          </label>
        </div>
      </div>

      <div v-if="!form.is_indirect" class="border-ligne grid grid-cols-2 gap-4 border-t pt-4">
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="account_type">Account type</label>
          <select
            id="account_type"
            v-model="form.account_type"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="cash">Cash</option>
            <option value="bank">Bank</option>
          </select>
        </div>
        <div v-if="form.account_type === 'bank'" class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="bank_account">Bank account</label>
          <select
            id="bank_account"
            v-model="form.bank_account"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>Select a bank account</option>
            <option v-for="a in bankAccounts" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>
        <div v-else class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="cash_account">Cash account</label>
          <select
            id="cash_account"
            v-model="form.cash_account"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>Select a cash account</option>
            <option v-for="a in cashAccounts" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>
      </div>

      <div class="border-ligne space-y-2 border-t pt-4">
        <div class="flex items-center justify-between">
          <h2 class="font-display text-sm font-semibold uppercase">Allocate to invoices</h2>
          <button type="button" class="text-texte-2 hover:text-texte text-sm" @click="addLine">
            + Add line
          </button>
        </div>
        <p v-if="loadingInvoices" class="text-texte-3 text-sm">Loading unpaid invoices…</p>

        <div v-for="(line, index) in lines" :key="index" class="flex items-center gap-2">
          <select
            v-model="line.invoice"
            class="border-ligne-forte h-12 flex-1 rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
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
            class="border-ligne-forte h-12 w-40 rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
          <button
            type="button"
            class="text-critique text-sm hover:brightness-90"
            @click="removeLine(index)"
          >
            Remove
          </button>
        </div>

        <p class="text-texte-2 text-sm">
          Allocated: {{ allocatedTotal.toLocaleString() }} · Remaining unallocated:
          <span :class="unallocatedRemainder < 0 ? 'text-critique font-medium' : ''">
            {{ unallocatedRemainder.toLocaleString() }}
          </span>
        </p>
      </div>

      <div class="flex justify-end">
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? 'Saving…' : 'Record payment' }}
        </Button>
      </div>
    </form>
  </div>
</template>
