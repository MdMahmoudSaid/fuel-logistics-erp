<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// docs/PHASE_4_PLAN.md Etape 9: invoice list with status filters. No "New"
// button - invoices are generated automatically by DeliveryService, never
// created directly (backend/apps/sales/views.py InvoiceViewSet.create()).
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { invoiceResource, validateInvoices } from './api'
import { translateApiError } from '@/i18n/apiErrors'
import { useAuthStore } from '@/stores/auth'
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
const auth = useAuthStore()
const canValidate = computed(() => auth.can('sales', 'validate'))

// Bulk validation: DRAFT invoices of ONE customer, ticked from the list.
const customerFilter = ref('')
const selectedIds = ref<number[]>([])
const bulkValidating = ref(false)
const bulkError = ref('')

const customerOptions = computed(() => {
  const seen = new Map<number, string>()
  for (const invoice of invoices.value) {
    const customer = invoice.sale_detail?.customer_detail
    if (customer) seen.set(customer.id, customer.name)
  }
  return [...seen.entries()].map(([id, name]) => ({ id, name }))
})
const visibleInvoices = computed(() =>
  customerFilter.value
    ? invoices.value.filter(
        (invoice) => String(invoice.sale_detail?.customer_detail?.id) === customerFilter.value,
      )
    : invoices.value,
)
const selectedCustomerId = computed(
  () =>
    invoices.value.find((invoice) => invoice.id === selectedIds.value[0])?.sale_detail
      ?.customer_detail?.id ?? null,
)
function canSelect(invoice: Invoice) {
  return (
    invoice.status === 'DRAFT' &&
    (selectedCustomerId.value === null ||
      invoice.sale_detail?.customer_detail?.id === selectedCustomerId.value)
  )
}
const selectableVisible = computed(() =>
  visibleInvoices.value.filter((invoice) => invoice.status === 'DRAFT'),
)
const allVisibleSelected = computed(
  () =>
    !!customerFilter.value &&
    selectableVisible.value.length > 0 &&
    selectableVisible.value.every((invoice) => selectedIds.value.includes(invoice.id)),
)
function toggleAllVisible() {
  selectedIds.value = allVisibleSelected.value ? [] : selectableVisible.value.map((i) => i.id)
}
function onCustomerFilterChange() {
  selectedIds.value = []
}
async function onBulkValidate() {
  bulkValidating.value = true
  bulkError.value = ''
  try {
    await validateInvoices(selectedIds.value)
    selectedIds.value = []
    await loadInvoices()
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    bulkError.value = translateApiError(detail) || t('sales.invoiceList.bulkValidateError')
  } finally {
    bulkValidating.value = false
  }
}
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
      <div class="flex gap-2">
        <Button
          v-if="canValidate && selectedIds.length"
          data-test="bulk-validate"
          :disabled="bulkValidating"
          @click="onBulkValidate"
        >
          {{
            bulkValidating
              ? t('sales.invoiceList.bulkValidating')
              : t('sales.invoiceList.bulkValidate', { count: selectedIds.length })
          }}
        </Button>
        <Button variant="primary" @click="openPaymentModal">
          {{ t('sales.invoiceList.newPayment') }}
        </Button>
      </div>
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
      <select
        v-model="customerFilter"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="onCustomerFilterChange"
      >
        <option value="">{{ t('sales.saleList.allCustomers') }}</option>
        <option v-for="c in customerOptions" :key="c.id" :value="String(c.id)">
          {{ c.name }}
        </option>
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

    <AppAlert v-if="error" :message="error" />
    <AppAlert v-if="bulkError" :message="bulkError" />

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th v-if="canValidate" class="w-10 px-3 py-2.5">
              <input
                type="checkbox"
                :checked="allVisibleSelected"
                :disabled="!customerFilter || !selectableVisible.length"
                :title="t('sales.invoiceList.selectionHint')"
                @change="toggleAllVisible"
              />
            </th>
            <th class="px-3 py-2.5 font-medium">
              {{ t('sales.invoiceList.table.invoiceNumber') }}
            </th>
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
            v-for="invoice in visibleInvoices"
            :key="invoice.id"
            class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
            @click="goToDetail(invoice)"
          >
            <td v-if="canValidate" class="px-3 py-2.5" @click.stop>
              <input
                v-model="selectedIds"
                type="checkbox"
                :value="invoice.id"
                :disabled="!canSelect(invoice)"
                :title="t('sales.invoiceList.selectionHint')"
              />
            </td>
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
          <tr v-if="!loading && visibleInvoices.length === 0">
            <td :colspan="canValidate ? 9 : 8" class="text-texte-3 px-3 py-8 text-center">
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
