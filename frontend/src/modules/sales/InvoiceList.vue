<script setup lang="ts">
// docs/PHASE_4_PLAN.md Etape 9: invoice list with status filters. No "New"
// button - invoices are generated automatically by DeliveryService, never
// created directly (backend/apps/sales/views.py InvoiceViewSet.create()).
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { invoiceResource } from './api'
import { formatMoney } from '@/utils/currency'
import type { Invoice, InvoiceStatus } from './types'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import Modal from '@/components/ui/Modal.vue'
import PaymentAllocationForm from '@/modules/finance/PaymentAllocationForm.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const invoices = ref<Invoice[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref<InvoiceStatus | ''>('')
const showPaymentModal = ref(false)
const paymentCustomerId = ref<number | null>(null)

const invoiceSummary = computed(() => {
  const total = invoices.value.reduce((sum, invoice) => sum + Number(invoice.total_amount), 0)
  const paid = invoices.value.reduce((sum, invoice) => sum + Number(invoice.paid_amount || 0), 0)
  const outstanding = invoices.value.reduce(
    (sum, invoice) => sum + Number(invoice.outstanding_amount || 0),
    0,
  )
  return {
    total,
    paid,
    outstanding,
    unpaidCount: invoices.value.filter((invoice) => invoice.status === 'VALIDATED').length,
    partialCount: invoices.value.filter((invoice) => invoice.status === 'PARTIALLY_PAID').length,
  }
})

function openPaymentModal() {
  paymentCustomerId.value = route.query.customer ? Number(route.query.customer) : null
  showPaymentModal.value = true
}

function onPaymentSuccess() {
  showPaymentModal.value = false
  loadInvoices()
}

async function loadInvoices() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string> = {}
    if (statusFilter.value) params.status = statusFilter.value
    const data = await invoiceResource.list(params)
    invoices.value = data.results
  } catch {
    error.value = t('sales.invoiceList.loadError')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadInvoices()
  if (route.query.action === 'payment') openPaymentModal()
})

function goToDetail(invoice: Invoice) {
  router.push({ name: 'invoice-detail', params: { id: invoice.id } })
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
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('sales.invoiceList.title') }}
      </h1>
      <Button variant="primary" @click="openPaymentModal">
        {{ t('sales.invoiceList.newPayment') }}
      </Button>
    </div>

    <div class="flex flex-wrap gap-3">
      <select
        v-model="statusFilter"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="loadInvoices"
      >
        <option value="">{{ t('sales.invoiceList.allStatuses') }}</option>
        <option value="DRAFT">{{ t('invoiceStatus.DRAFT') }}</option>
        <option value="VALIDATED">{{ t('invoiceStatus.VALIDATED') }}</option>
        <option value="PARTIALLY_PAID">{{ t('invoiceStatus.PARTIALLY_PAID') }}</option>
        <option value="PAID">{{ t('invoiceStatus.PAID') }}</option>
        <option value="CANCELLED">{{ t('invoiceStatus.CANCELLED') }}</option>
      </select>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <div class="border-ligne rounded-lg border bg-white p-4">
        <p class="text-texte-2 text-xs font-semibold uppercase">Total facturé</p>
        <p class="font-mono text-lg font-semibold">{{ formatMoney(invoiceSummary.total) }}</p>
      </div>
      <div class="border-ligne rounded-lg border bg-white p-4">
        <p class="text-texte-2 text-xs font-semibold uppercase">Total encaissé</p>
        <p class="font-mono text-lg font-semibold">{{ formatMoney(invoiceSummary.paid) }}</p>
      </div>
      <div class="border-ligne rounded-lg border bg-white p-4">
        <p class="text-texte-2 text-xs font-semibold uppercase">Reste à encaisser</p>
        <p class="font-mono text-lg font-semibold">{{ formatMoney(invoiceSummary.outstanding) }}</p>
      </div>
      <div class="border-ligne rounded-lg border bg-white p-4">
        <p class="text-texte-2 text-xs font-semibold uppercase">Factures impayées</p>
        <p class="font-mono text-lg font-semibold">{{ invoiceSummary.unpaidCount }}</p>
      </div>
      <div class="border-ligne rounded-lg border bg-white p-4">
        <p class="text-texte-2 text-xs font-semibold uppercase">Partiellement payées</p>
        <p class="font-mono text-lg font-semibold">{{ invoiceSummary.partialCount }}</p>
      </div>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">{{ t('sales.invoiceList.table.invoiceNumber') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('sales.invoiceList.table.customer') }}</th>
            <th class="px-3 py-2.5 text-right font-medium">
              {{ t('sales.invoiceList.table.total') }}
            </th>
            <th class="px-3 py-2.5 text-right font-medium">Déjà payé</th>
            <th class="px-3 py-2.5 text-right font-medium">Reste à payer</th>
            <th class="px-3 py-2.5 font-medium">{{ t('sales.invoiceList.table.issued') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('sales.invoiceList.table.status') }}</th>
            <th class="px-3 py-2.5 font-medium">Action</th>
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
              <MonoValue :value="formatMoney(invoice.total_amount)" />
            </td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="formatMoney(invoice.paid_amount || 0)" />
            </td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="formatMoney(invoice.outstanding_amount || 0)" />
            </td>
            <td class="px-3 py-2.5">{{ invoice.issued_date }}</td>
            <td class="px-3 py-2.5">
              <Badge :variant="badgeVariant(invoice.status)">{{
                t(`invoiceStatus.${invoice.status}`)
              }}</Badge>
            </td>
            <td class="px-3 py-2.5">Détail / paiement</td>
          </tr>
          <tr v-if="!loading && invoices.length === 0">
            <td colspan="8" class="text-texte-3 px-3 py-8 text-center">
              {{ t('sales.invoiceList.noInvoices') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Modal
      v-if="showPaymentModal"
      :title="t('finance.payment.title')"
      max-width="max-w-3xl"
      @close="showPaymentModal = false"
    >
      <PaymentAllocationForm
        :initial-customer-id="paymentCustomerId"
        @success="onPaymentSuccess"
        @cancel="showPaymentModal = false"
      />
    </Modal>
  </div>
</template>
