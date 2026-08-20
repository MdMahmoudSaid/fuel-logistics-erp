<script setup lang="ts">
// docs/PHASE_4_PLAN.md Etape 9: invoice list with status filters. No "New"
// button - invoices are generated automatically by DeliveryService, never
// created directly (backend/apps/sales/views.py InvoiceViewSet.create()).
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { invoiceResource } from './api'
import type { Invoice, InvoiceStatus } from './types'
import Badge from '@/components/ui/Badge.vue'
import MonoValue from '@/components/ui/MonoValue.vue'

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

const STATUS_LABEL: Record<string, string> = {
  DRAFT: 'Draft',
  VALIDATED: 'Validated',
  PARTIALLY_PAID: 'Partially paid',
  PAID: 'Paid',
  CANCELLED: 'Cancelled',
}

function badgeVariant(status: string) {
  if (status === 'PAID') return 'livre' as const
  if (status === 'VALIDATED') return 'transit' as const
  if (status === 'PARTIALLY_PAID') return 'ecart' as const
  if (status === 'CANCELLED') return 'critique' as const
  return 'neutre' as const
}
</script>

<template>
  <div class="space-y-4">
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">Invoices</h1>

    <div class="flex flex-wrap gap-3">
      <select
        v-model="statusFilter"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
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

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">Invoice #</th>
            <th class="px-3 py-2.5 font-medium">Customer</th>
            <th class="px-3 py-2.5 text-right font-medium">Total</th>
            <th class="px-3 py-2.5 font-medium">Issued</th>
            <th class="px-3 py-2.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="invoice in invoices"
            :key="invoice.id"
            class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
            @click="goToDetail(invoice)"
          >
            <td class="px-3 py-2.5"><MonoValue :value="invoice.invoice_number" align="left" /></td>
            <td class="px-3 py-2.5">{{ invoice.sale_detail?.customer_detail?.name }}</td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue
                :value="Number(invoice.total_amount).toLocaleString()"
                :unit="invoice.sale_detail?.currency"
              />
            </td>
            <td class="px-3 py-2.5">{{ invoice.issued_date }}</td>
            <td class="px-3 py-2.5">
              <Badge :variant="badgeVariant(invoice.status)">{{
                STATUS_LABEL[invoice.status]
              }}</Badge>
            </td>
          </tr>
          <tr v-if="!loading && invoices.length === 0">
            <td colspan="5" class="text-texte-3 px-3 py-8 text-center">No invoices yet.</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
