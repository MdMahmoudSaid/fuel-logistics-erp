<script setup lang="ts">
// docs/PHASE_4_PLAN.md Etape 9: invoice list with status filters. No "New"
// button - invoices are generated automatically by DeliveryService, never
// created directly (backend/apps/sales/views.py InvoiceViewSet.create()).
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { invoiceResource } from './api'
import type { Invoice, InvoiceStatus } from './types'

const router = useRouter()

const invoices = ref<Invoice[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref<InvoiceStatus | ''>('')

async function loadInvoices() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string> = {}
    if (statusFilter.value) params.status = statusFilter.value
    const data = await invoiceResource.list(params)
    invoices.value = data.results
  } catch {
    error.value = 'Could not load invoices.'
  } finally {
    loading.value = false
  }
}

onMounted(loadInvoices)

function goToDetail(invoice: Invoice) {
  router.push({ name: 'invoice-detail', params: { id: invoice.id } })
}

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-slate-100 text-slate-600',
  VALIDATED: 'bg-sky-100 text-sky-700',
  PARTIALLY_PAID: 'bg-amber-100 text-amber-700',
  PAID: 'bg-emerald-100 text-emerald-700',
  CANCELLED: 'bg-red-100 text-red-700',
}
</script>

<template>
  <div class="space-y-4">
    <h2 class="text-lg font-semibold text-slate-800">Invoices</h2>

    <div class="flex flex-wrap gap-3 rounded border bg-white p-3">
      <select
        v-model="statusFilter"
        class="rounded border border-slate-300 px-2 py-1.5 text-sm"
        @change="loadInvoices"
      >
        <option value="">All statuses</option>
        <option value="DRAFT">Draft</option>
        <option value="VALIDATED">Validated</option>
        <option value="PARTIALLY_PAID">Partially paid</option>
        <option value="PAID">Paid</option>
        <option value="CANCELLED">Cancelled</option>
      </select>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <div class="overflow-x-auto rounded border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-b text-slate-500">
            <th class="px-3 py-2 font-medium">Invoice #</th>
            <th class="px-3 py-2 font-medium">Customer</th>
            <th class="px-3 py-2 font-medium text-right">Total</th>
            <th class="px-3 py-2 font-medium">Issued</th>
            <th class="px-3 py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="invoice in invoices"
            :key="invoice.id"
            class="cursor-pointer border-b last:border-0 hover:bg-slate-50"
            @click="goToDetail(invoice)"
          >
            <td class="px-3 py-2 font-medium text-slate-800">{{ invoice.invoice_number }}</td>
            <td class="px-3 py-2">{{ invoice.sale_detail?.customer_detail?.name }}</td>
            <td class="px-3 py-2 text-right">
              {{ Number(invoice.total_amount).toLocaleString() }}
              {{ invoice.sale_detail?.currency }}
            </td>
            <td class="px-3 py-2">{{ invoice.issued_date }}</td>
            <td class="px-3 py-2">
              <span
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :class="STATUS_BADGE[invoice.status]"
              >
                {{ invoice.status }}
              </span>
            </td>
          </tr>
          <tr v-if="!loading && invoices.length === 0">
            <td colspan="5" class="px-3 py-6 text-center text-slate-400">No invoices yet.</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
