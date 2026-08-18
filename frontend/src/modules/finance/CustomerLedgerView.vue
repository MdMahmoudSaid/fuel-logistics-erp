<script setup lang="ts">
// Companion page to backend GET /api/customers/{id}/ledger/
// (docs/PHASE_5_PLAN.md Etape 8/10), mirroring the existing
// SupplierLedgerView.vue pattern.
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchCustomerLedger } from './api'
import type { CustomerLedger } from './types'

const route = useRoute()
const router = useRouter()

const ledger = ref<CustomerLedger | null>(null)
const loading = ref(true)
const error = ref('')

const customerId = computed(() => Number(route.params.id))

async function load() {
  loading.value = true
  error.value = ''
  try {
    ledger.value = await fetchCustomerLedger(customerId.value)
  } catch {
    error.value = 'Could not load the customer ledger.'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-slate-100 text-slate-600',
  VALIDATED: 'bg-sky-100 text-sky-700',
  PARTIALLY_PAID: 'bg-amber-100 text-amber-700',
  PAID: 'bg-emerald-100 text-emerald-700',
  CANCELLED: 'bg-red-100 text-red-700',
}
</script>

<template>
  <div class="max-w-4xl space-y-6">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">
        Customer Ledger — {{ ledger?.customer.name ?? '…' }}
      </h2>
      <div class="flex gap-2">
        <button
          class="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white"
          @click="
            router.push({ name: 'customer-payment-new', query: { customer: String(customerId) } })
          "
        >
          New payment
        </button>
        <button
          class="px-3 py-2 text-sm text-slate-500"
          @click="router.push({ name: 'customers' })"
        >
          Back
        </button>
      </div>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">Loading…</p>

    <template v-else-if="ledger">
      <section class="rounded border bg-white p-4">
        <p class="text-xs text-slate-500">Outstanding balance</p>
        <p
          class="text-lg font-semibold"
          :class="Number(ledger.outstanding_balance) > 0 ? 'text-amber-600' : 'text-emerald-600'"
        >
          {{ Number(ledger.outstanding_balance).toLocaleString() }}
        </p>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-base font-semibold text-slate-800">Invoices</h3>
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-b text-slate-500">
              <th class="px-2 py-1.5 font-medium">Invoice</th>
              <th class="px-2 py-1.5 font-medium">Issued</th>
              <th class="px-2 py-1.5 font-medium text-right">Total</th>
              <th class="px-2 py-1.5 font-medium text-right">Outstanding</th>
              <th class="px-2 py-1.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="invoice in ledger.invoices"
              :key="invoice.id"
              class="cursor-pointer border-b last:border-0 hover:bg-slate-50"
              @click="router.push({ name: 'invoice-detail', params: { id: invoice.id } })"
            >
              <td class="px-2 py-1.5 font-medium text-slate-800">{{ invoice.invoice_number }}</td>
              <td class="px-2 py-1.5">{{ invoice.issued_date }}</td>
              <td class="px-2 py-1.5 text-right">
                {{ Number(invoice.total_amount).toLocaleString() }}
              </td>
              <td class="px-2 py-1.5 text-right font-medium text-slate-800">
                {{ Number(invoice.outstanding).toLocaleString() }}
              </td>
              <td class="px-2 py-1.5">
                <span
                  class="rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="STATUS_BADGE[invoice.status]"
                >
                  {{ invoice.status }}
                </span>
              </td>
            </tr>
            <tr v-if="ledger.invoices.length === 0">
              <td colspan="5" class="px-2 py-4 text-center text-slate-400">No invoices yet.</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-base font-semibold text-slate-800">Payments</h3>
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-b text-slate-500">
              <th class="px-2 py-1.5 font-medium">Date</th>
              <th class="px-2 py-1.5 font-medium">Method</th>
              <th class="px-2 py-1.5 font-medium">Indirect</th>
              <th class="px-2 py-1.5 font-medium">Reference</th>
              <th class="px-2 py-1.5 font-medium text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="payment in ledger.payments" :key="payment.id" class="border-b last:border-0">
              <td class="px-2 py-1.5">{{ payment.payment_date }}</td>
              <td class="px-2 py-1.5">{{ payment.method }}</td>
              <td class="px-2 py-1.5">{{ payment.is_indirect ? 'Yes' : 'No' }}</td>
              <td class="px-2 py-1.5">{{ payment.reference || '—' }}</td>
              <td class="px-2 py-1.5 text-right font-medium text-slate-800">
                {{ Number(payment.amount).toLocaleString() }}
              </td>
            </tr>
            <tr v-if="ledger.payments.length === 0">
              <td colspan="5" class="px-2 py-4 text-center text-slate-400">No payments yet.</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
