<script setup lang="ts">
// Companion page to backend GET /api/customers/{id}/ledger/
// (docs/PHASE_5_PLAN.md Etape 8/10), mirroring the existing
// SupplierLedgerView.vue pattern.
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { fetchCustomerLedger, exportLedgerPdf, exportCustomerPaymentPdf } from './api'
import { exportInvoicePdf } from '@/modules/sales/api'
import Modal from '@/components/ui/Modal.vue'
import PaymentAllocationForm from './PaymentAllocationForm.vue'
import type { CustomerLedger } from './types'
import { formatMoney, formatQuantity } from '@/utils/currency'
import AppLogo from '@/components/AppLogo.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import MonoValue from '@/components/ui/MonoValue.vue'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()

const ledger = ref<CustomerLedger | null>(null)
const loading = ref(true)
const error = ref('')
const exporting = ref(false)
const exportingPaymentId = ref<number | null>(null)
const exportingInvoiceId = ref<number | null>(null)

const customerId = computed(() => Number(route.params.id))
const showPaymentModal = ref(false)
const previewUrl = ref<string | null>(null)
const IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp']

function isImageUrl(url: string): boolean {
  const path = url.split('?')[0].toLowerCase()
  return IMAGE_EXTENSIONS.some((ext) => path.endsWith(ext))
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    ledger.value = await fetchCustomerLedger(customerId.value)
  } catch {
    error.value = t('finance.customerLedger.loadError')
  } finally {
    loading.value = false
  }
}

function onPaymentSuccess() {
  showPaymentModal.value = false
  load()
}

function printLedger() {
  window.print()
}

async function exportPdf() {
  exporting.value = true
  try {
    await exportLedgerPdf('customer', customerId.value, locale.value)
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exporting.value = false
  }
}

async function exportInvoicePdfRow(invoiceId: number) {
  exportingInvoiceId.value = invoiceId
  try {
    await exportInvoicePdf(invoiceId, locale.value)
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exportingInvoiceId.value = null
  }
}

async function exportPaymentPdf(paymentId: number) {
  exportingPaymentId.value = paymentId
  try {
    await exportCustomerPaymentPdf(paymentId, locale.value)
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exportingPaymentId.value = null
  }
}

onMounted(load)

const totalInvoiced = computed(
  () =>
    ledger.value?.invoices.reduce((total, invoice) => total + Number(invoice.total_amount), 0) ?? 0,
)
const totalReceived = computed(
  () => ledger.value?.payments.reduce((total, payment) => total + Number(payment.amount), 0) ?? 0,
)
const openInvoices = computed(
  () =>
    ledger.value?.invoices.filter(
      (invoice) => Number(invoice.outstanding) > 0 && invoice.status !== 'CANCELLED',
    ).length ?? 0,
)
const lastPayment = computed(() => {
  const payments = [...(ledger.value?.payments ?? [])]
  return payments.sort((a, b) => b.payment_date.localeCompare(a.payment_date))[0] ?? null
})

function badgeVariant(status: string) {
  if (status === 'PAID') return 'livre' as const
  if (status === 'CANCELLED') return 'critique' as const
  if (status === 'PARTIALLY_PAID') return 'ecart' as const
  return 'neutre' as const
}
</script>

<template>
  <div class="max-w-4xl space-y-6">
    <!-- Print-only branding + hidden action row, see SupplierLedgerView.vue
    for the full rationale (client feedback 2026-09-06). -->
    <div class="hidden items-center gap-2.5 print:mb-2 print:flex">
      <AppLogo :size="36" />
    </div>
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('finance.customerLedger.title', { name: ledger?.customer.name ?? '…' }) }}
      </h1>
      <div class="no-print flex flex-wrap gap-2">
        <Button v-if="ledger" variant="primary" @click="showPaymentModal = true">
          {{ t('finance.customerLedger.newPayment') }}
        </Button>
        <Button v-if="ledger" variant="ghost" @click="printLedger">
          {{ t('reports.print') }}
        </Button>
        <Button v-if="ledger" variant="ghost" :disabled="exporting" @click="exportPdf">
          {{ t('reports.exportPdf') }}
        </Button>
        <Button variant="ghost" @click="router.push({ name: 'customers' })">
          {{ t('finance.customerLedger.back') }}
        </Button>
      </div>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else-if="ledger">
      <section class="grid gap-3 md:grid-cols-5">
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.customerLedger.totalInvoiced') }}
          </p>
          <MonoValue class="font-semibold" align="left" :value="formatMoney(totalInvoiced)" />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.customerLedger.totalReceived') }}
          </p>
          <MonoValue class="font-semibold" align="left" :value="formatMoney(totalReceived)" />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.customerLedger.outstandingBalance') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :class="Number(ledger.outstanding_balance) > 0 ? 'text-ecart' : 'text-livre'"
            :value="formatMoney(ledger.outstanding_balance)"
          />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.customerLedger.openInvoices') }}
          </p>
          <MonoValue class="font-semibold" align="left" :value="String(openInvoices)" />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.customerLedger.lastPayment') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :value="lastPayment ? formatMoney(lastPayment.amount) : '—'"
          />
        </div>
      </section>

      <Card :title="t('finance.customerLedger.invoices')">
        <div class="overflow-x-auto">
          <table class="w-full text-start text-sm">
            <thead>
              <tr class="border-ligne text-texte-2 border-b">
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.customerLedger.table.invoice') }}
                </th>
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.customerLedger.table.issued') }}
                </th>
                <th class="px-2 py-1.5 font-medium text-right">
                  {{ t('finance.customerLedger.table.loadedQuantity') }}
                </th>
                <th class="px-2 py-1.5 font-medium text-right">
                  {{ t('finance.customerLedger.table.receivedQuantity') }}
                </th>
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.customerLedger.table.truckPlates') }}
                </th>
                <th class="px-2 py-1.5 font-medium text-right">
                  {{ t('finance.customerLedger.table.total') }}
                </th>
                <th class="px-2 py-1.5 font-medium text-right">
                  {{ t('finance.customerLedger.table.outstanding') }}
                </th>
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.customerLedger.table.status') }}
                </th>
                <th class="px-2 py-1.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="invoice in ledger.invoices"
                :key="invoice.id"
                class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
                @click="router.push({ name: 'invoice-detail', params: { id: invoice.id } })"
              >
                <td class="text-texte px-2 py-1.5 font-medium">{{ invoice.invoice_number }}</td>
                <td class="px-2 py-1.5">{{ invoice.issued_date }}</td>
                <td class="px-2 py-1.5 text-right">
                  <MonoValue
                    :value="
                      invoice.sale_detail
                        ? formatQuantity(invoice.sale_detail.quantity_loaded)
                        : ''
                    "
                  />
                </td>
                <td class="px-2 py-1.5 text-right">
                  <MonoValue
                    :value="
                      invoice.sale_detail
                        ? formatQuantity(invoice.sale_detail.delivered_quantity)
                        : ''
                    "
                  />
                </td>
                <td class="px-2 py-1.5">{{ invoice.sale_detail?.truck_plates ?? '—' }}</td>
                <td class="px-2 py-1.5 text-right">
                  {{ formatMoney(invoice.total_amount) }}
                </td>
                <td class="text-texte px-2 py-1.5 text-right font-medium">
                  {{ formatMoney(invoice.outstanding) }}
                </td>
                <td class="px-2 py-1.5">
                  <Badge :variant="badgeVariant(invoice.status)">
                    {{ t(`invoiceStatus.${invoice.status}`) }}
                  </Badge>
                </td>
                <td class="px-2 py-1.5 text-right">
                  <button
                    type="button"
                    data-test="customer-invoice-pdf"
                    class="text-bitume underline disabled:opacity-50"
                    :disabled="exportingInvoiceId === invoice.id"
                    @click.stop="exportInvoicePdfRow(invoice.id)"
                  >
                    {{ t('finance.partyLedger.pdf') }}
                  </button>
                </td>
              </tr>
              <tr v-if="ledger.invoices.length === 0">
                <td colspan="9" class="text-texte-3 px-2 py-4 text-center">
                  {{ t('finance.customerLedger.noInvoices') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card :title="t('finance.customerLedger.payments')">
        <div class="overflow-x-auto">
          <table class="w-full text-start text-sm">
            <thead>
              <tr class="border-ligne text-texte-2 border-b">
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.customerLedger.paymentsTable.date') }}
                </th>
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.customerLedger.paymentsTable.method') }}
                </th>
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.customerLedger.paymentsTable.indirect') }}
                </th>
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.customerLedger.paymentsTable.reference') }}
                </th>
                <th class="px-2 py-1.5 font-medium text-right">
                  {{ t('finance.customerLedger.paymentsTable.amount') }}
                </th>
                <th class="px-2 py-1.5 font-medium">Justificatif</th>
                <th class="px-2 py-1.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="payment in ledger.payments"
                :key="payment.id"
                class="border-ligne border-b last:border-0"
              >
                <td class="px-2 py-1.5">{{ payment.payment_date }}</td>
                <td class="px-2 py-1.5">{{ t(`paymentMethod.${payment.method}`) }}</td>
                <td class="px-2 py-1.5">
                  {{ payment.is_indirect ? t('common.yes') : t('common.no') }}
                </td>
                <td class="px-2 py-1.5">{{ payment.reference || '—' }}</td>
                <td class="text-texte px-2 py-1.5 text-right font-medium">
                  <MonoValue :value="formatMoney(payment.amount)" />
                </td>
                <td class="px-2 py-1.5">
                  <button
                    v-if="payment.proof_url"
                    type="button"
                    class="text-bitume underline"
                    @click="previewUrl = payment.proof_url"
                  >
                    Voir justificatif
                  </button>
                  <span v-else class="text-texte-3">—</span>
                </td>
                <td class="px-2 py-1.5 text-right">
                  <button
                    type="button"
                    data-test="customer-payment-pdf"
                    class="text-bitume underline disabled:opacity-50"
                    :disabled="exportingPaymentId === payment.id"
                    @click="exportPaymentPdf(payment.id)"
                  >
                    {{ t('finance.partyLedger.pdf') }}
                  </button>
                </td>
              </tr>
              <tr v-if="ledger.payments.length === 0">
                <td colspan="7" class="text-texte-3 px-2 py-4 text-center">
                  {{ t('finance.customerLedger.noPayments') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
    </template>

    <Modal
      v-if="showPaymentModal"
      :title="t('finance.payment.title')"
      max-width="max-w-3xl"
      @close="showPaymentModal = false"
    >
      <PaymentAllocationForm
        :initial-customer-id="customerId"
        @success="onPaymentSuccess"
        @cancel="showPaymentModal = false"
      />
    </Modal>

    <Modal
      v-if="previewUrl"
      :title="t('finance.customerLedger.paymentsTable.proof')"
      max-width="max-w-3xl"
      @close="previewUrl = null"
    >
      <img
        v-if="isImageUrl(previewUrl)"
        :src="previewUrl"
        class="max-h-[80vh] w-full rounded-lg object-contain"
      />
      <div v-else class="space-y-3">
        <iframe
          v-if="previewUrl.toLowerCase().includes('.pdf')"
          :src="previewUrl"
          class="h-[80vh] w-full rounded-lg"
        />
        <a :href="previewUrl" download class="text-bitume underline">
          {{ t('finance.customerLedger.downloadProof') }}
        </a>
      </div>
      <div class="mt-4 flex justify-end">
        <Button variant="ghost" @click="previewUrl = null">{{ t('common.close') }}</Button>
      </div>
    </Modal>
  </div>
</template>
