<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { fetchSupplierLedger } from '@/modules/purchasing/api'
import { cancelSupplierPayment, exportLedgerPdf, exportSupplierPaymentPdf } from '@/modules/finance/api'
import type { SupplierLedger } from '@/modules/purchasing/types'
import DebtPaymentForm from '@/modules/finance/DebtPaymentForm.vue'
import AdvanceForm from '@/modules/finance/AdvanceForm.vue'
import { formatMoney, formatQuantity } from '@/utils/currency'
import AppLogo from '@/components/AppLogo.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Modal from '@/components/ui/Modal.vue'
import MonoValue from '@/components/ui/MonoValue.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t, locale } = useI18n()

const ledger = ref<SupplierLedger | null>(null)
const loading = ref(true)
const error = ref('')
const showPaymentForm = ref(false)
const showAdvanceForm = ref(false)
const previewUrl = ref<string | null>(null)
const exporting = ref(false)
const exportingPaymentId = ref<number | null>(null)
const cancellingPaymentId = ref<number | null>(null)
const cancelError = ref('')

const canCancelSupplierPayments = computed(() => auth.can('finance', 'cancel'))

const supplierId = computed(() => Number(route.params.id))

async function load() {
  loading.value = true
  error.value = ''
  try {
    ledger.value = await fetchSupplierLedger(supplierId.value)
  } catch {
    error.value = t('purchasing.supplierLedger.loadError')
  } finally {
    loading.value = false
  }
}

async function onPaymentSaved() {
  showPaymentForm.value = false
  await load()
}

async function onAdvanceSaved() {
  showAdvanceForm.value = false
  await load()
}

function printLedger() {
  window.print()
}

async function exportPdf() {
  exporting.value = true
  try {
    await exportLedgerPdf('supplier', supplierId.value, locale.value)
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exporting.value = false
  }
}

async function exportPaymentPdf(paymentId: number) {
  exportingPaymentId.value = paymentId
  try {
    await exportSupplierPaymentPdf(paymentId, locale.value)
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exportingPaymentId.value = null
  }
}

async function onCancelSupplierPayment(paymentId: number) {
  if (!window.confirm(t('purchasing.supplierLedger.paymentsTable.cancelConfirm'))) return
  cancellingPaymentId.value = paymentId
  cancelError.value = ''
  try {
    await cancelSupplierPayment(paymentId)
    await load()
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    cancelError.value = detail || t('purchasing.supplierLedger.paymentsTable.cancelError')
  } finally {
    cancellingPaymentId.value = null
  }
}

onMounted(load)

const lastOperation = computed(() => {
  const advance = ledger.value?.summary.last_advance ?? null
  const payment = ledger.value?.summary.last_payment ?? null
  if (advance && payment) {
    return advance.date >= payment.date
      ? { kind: 'advance' as const, amount: advance.amount }
      : { kind: 'payment' as const, amount: payment.amount }
  }
  if (advance) return { kind: 'advance' as const, amount: advance.amount }
  if (payment) return { kind: 'payment' as const, amount: payment.amount }
  return null
})

function badgeVariant(status: string) {
  if (status === 'CONFIRMED') return 'livre' as const
  if (status === 'CANCELLED') return 'critique' as const
  return 'neutre' as const
}

function proofUrl(order: SupplierLedger['orders'][number]) {
  return order.documents[0]?.file ?? null
}
</script>

<template>
  <div class="max-w-4xl space-y-6">
    <!-- Print-only branding (client feedback 2026-09-06): window.print()
    prints this page's own content, not a generated PDF - it had no logo/
    company name of its own (only whatever the browser's own optional
    print header shows) and the action buttons below printed right along
    with the data. Hidden on screen, shown only in the print stylesheet;
    the buttons row gets .no-print instead. -->
    <div class="hidden items-center gap-2.5 print:mb-2 print:flex">
      <AppLogo :size="36" />
    </div>
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('purchasing.supplierLedger.title', { name: ledger?.supplier.name ?? '…' }) }}
      </h1>
      <div class="no-print flex flex-wrap gap-2">
        <Button
          v-if="ledger && Number(ledger.summary.net_balance) < 0"
          variant="primary"
          @click="showPaymentForm = true"
        >
          {{ t('finance.supplierPayment.recordPayment') }}
        </Button>
        <Button
          v-if="ledger && Number(ledger.summary.net_balance) >= 0"
          variant="secondary"
          @click="showAdvanceForm = true"
        >
          {{ t('finance.advanceForm.title') }}
        </Button>
        <Button v-if="ledger" variant="ghost" @click="printLedger">
          {{ t('reports.print') }}
        </Button>
        <Button v-if="ledger" variant="ghost" :disabled="exporting" @click="exportPdf">
          {{ t('reports.exportPdf') }}
        </Button>
        <Button variant="ghost" @click="router.push({ name: 'suppliers' })">
          {{ t('purchasing.supplierLedger.back') }}
        </Button>
      </div>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else-if="ledger">
      <section class="grid gap-3 md:grid-cols-4">
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.partyLedger.totalDue') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :value="formatMoney(ledger.summary.total_due)"
          />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.partyLedger.openAdvances') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :value="formatMoney(ledger.summary.open_advances)"
          />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.partyLedger.netBalance') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :class="Number(ledger.summary.net_balance) < 0 ? 'text-critique' : 'text-livre'"
            :value="formatMoney(ledger.summary.net_balance)"
          />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.partyLedger.lastMovement') }}
          </p>
          <p class="text-texte text-sm">
            <template v-if="lastOperation">
              {{ t(`finance.partyLedger.${lastOperation.kind}`) }}:
              {{ formatMoney(lastOperation.amount) }}
            </template>
            <template v-else>—</template>
          </p>
        </div>
      </section>

      <Card :title="t('purchasing.supplierLedger.reliquatByProduct')">
        <div class="overflow-x-auto">
          <table class="w-full text-start text-sm">
            <thead>
              <tr class="border-ligne text-texte-2 border-b">
                <th class="px-3 py-2.5 font-medium">{{ t('purchasing.supplierLedger.product') }}</th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('purchasing.supplierLedger.totalReliquat') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in ledger.reliquat_summary"
                :key="item.product_id"
                class="border-ligne border-b last:border-0"
              >
                <td class="px-3 py-2.5">{{ item.product_name }}</td>
                <td class="px-3 py-2.5 text-end">
                  <MonoValue
                    :class="Number(item.total_reliquat) <= 0 ? 'text-critique' : 'text-texte'"
                    :value="formatQuantity(item.total_reliquat)"
                  />
                </td>
              </tr>
              <tr v-if="ledger.reliquat_summary.length === 0">
                <td colspan="2" class="text-texte-3 px-3 py-8 text-center">
                  {{ t('purchasing.supplierLedger.noPurchaseHistory') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card :title="t('purchasing.supplierLedger.purchaseHistory')">
        <div class="overflow-x-auto">
          <table class="w-full text-start text-sm">
            <thead>
              <tr class="border-ligne text-texte-2 border-b">
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.table.reference') }}
                </th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.table.product') }}
                </th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.table.date') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('purchasing.supplierLedger.table.purchased') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('purchasing.supplierLedger.table.reliquat') }}
                </th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.table.status') }}
                </th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.table.proof') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="order in ledger.orders"
                :key="order.id"
                class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
                @click="router.push({ name: 'supplier-order-detail', params: { id: order.id } })"
              >
                <td class="px-3 py-2.5"><MonoValue :value="order.reference" align="left" /></td>
                <td class="px-3 py-2.5">{{ order.product_detail?.name }}</td>
                <td class="px-3 py-2.5">{{ order.purchase_date }}</td>
                <td class="px-3 py-2.5 text-end">
                  <MonoValue :value="formatQuantity(order.quantity_litres)" />
                </td>
                <td class="px-3 py-2.5 text-end">
                  <MonoValue
                    :class="Number(order.reliquat) <= 0 ? 'text-critique' : 'text-texte'"
                    :value="formatQuantity(order.reliquat)"
                  />
                </td>
                <td class="px-3 py-2.5">
                  <Badge :variant="badgeVariant(order.status)">{{
                    t(`supplierOrderStatus.${order.status}`)
                  }}</Badge>
                </td>
                <td class="px-3 py-2.5">
                  <button
                    v-if="proofUrl(order)"
                    type="button"
                    class="text-bitume underline"
                    @click.stop="previewUrl = proofUrl(order)"
                  >
                    {{ t('purchasing.supplierLedger.viewProof') }}
                  </button>
                  <span v-else class="text-texte-3">—</span>
                </td>
              </tr>
              <tr v-if="ledger.orders.length === 0">
                <td colspan="7" class="text-texte-3 px-3 py-8 text-center">
                  {{ t('purchasing.supplierLedger.noPurchaseHistory') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card :title="t('purchasing.supplierLedger.paymentsAndAdvances')">
        <p v-if="cancelError" class="text-critique mb-2 text-sm">{{ cancelError }}</p>
        <div class="overflow-x-auto">
          <table class="w-full text-start text-sm">
            <thead>
              <tr class="border-ligne text-texte-2 border-b">
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.paymentsTable.date') }}
                </th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.paymentsTable.method') }}
                </th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.paymentsTable.reference') }}
                </th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.paymentsTable.advance') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('purchasing.supplierLedger.paymentsTable.amount') }}
                </th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.paymentsTable.status') }}
                </th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('purchasing.supplierLedger.paymentsTable.proof') }}
                </th>
                <th class="px-3 py-2.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="payment in ledger.payments"
                :key="payment.id"
                class="border-ligne border-b last:border-0"
                :class="payment.is_reversed ? 'opacity-60' : ''"
              >
                <td class="px-3 py-2.5">{{ payment.payment_date }}</td>
                <td class="px-3 py-2.5">{{ t(`paymentMethod.${payment.method}`) }}</td>
                <td class="px-3 py-2.5">{{ payment.reference || '—' }}</td>
                <td class="px-3 py-2.5">
                  {{ payment.is_advance ? t('common.yes') : t('common.no') }}
                </td>
                <td class="px-3 py-2.5 text-end">
                  <MonoValue
                    :class="payment.is_reversed ? 'text-texte-3 line-through' : ''"
                    :value="formatMoney(payment.amount)"
                  />
                </td>
                <td class="px-3 py-2.5">
                  <Badge v-if="payment.is_reversed" variant="critique">
                    {{ t('purchasing.supplierLedger.paymentsTable.cancelled') }}
                  </Badge>
                  <span v-else class="text-texte-3">—</span>
                </td>
                <td class="px-3 py-2.5">
                  <button
                    v-if="payment.proof_url"
                    type="button"
                    class="text-bitume underline"
                    @click="previewUrl = payment.proof_url"
                  >
                    {{ t('purchasing.supplierLedger.viewProof') }}
                  </button>
                  <span v-else class="text-texte-3">—</span>
                </td>
                <td class="px-3 py-2.5 text-end">
                  <div class="flex justify-end gap-3">
                    <button
                      type="button"
                      data-test="supplier-payment-pdf"
                      class="text-bitume underline disabled:opacity-50"
                      :disabled="exportingPaymentId === payment.id"
                      @click="exportPaymentPdf(payment.id)"
                    >
                      {{ t('finance.partyLedger.pdf') }}
                    </button>
                    <button
                      v-if="canCancelSupplierPayments && !payment.is_reversed"
                      type="button"
                      data-test="supplier-payment-cancel"
                      class="text-critique disabled:opacity-50"
                      :disabled="cancellingPaymentId === payment.id"
                      @click="onCancelSupplierPayment(payment.id)"
                    >
                      {{ t('purchasing.supplierLedger.paymentsTable.cancel') }}
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="ledger.payments.length === 0">
                <td colspan="8" class="text-texte-3 px-3 py-8 text-center">
                  {{ t('purchasing.supplierLedger.noPayments') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card :title="t('finance.partyLedger.entriesTitle')">
        <div class="overflow-x-auto">
          <table class="w-full text-start text-sm">
            <thead>
              <tr class="border-ligne text-texte-2 border-b">
                <th class="px-3 py-2.5 font-medium">{{ t('finance.partyLedger.table.date') }}</th>
                <th class="px-3 py-2.5 font-medium">{{ t('finance.partyLedger.table.type') }}</th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('finance.partyLedger.table.reference') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.partyLedger.table.amount') }}
                </th>
                <th class="px-3 py-2.5 font-medium">{{ t('finance.partyLedger.table.proof') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(entry, index) in ledger.entries"
                :key="index"
                class="border-ligne border-b last:border-0"
              >
                <td class="px-3 py-2.5">{{ entry.date }}</td>
                <td class="px-3 py-2.5">{{ t(`finance.partyLedger.entryTypes.${entry.type}`) }}</td>
                <td class="px-3 py-2.5">{{ entry.reference || '—' }}</td>
                <td class="px-3 py-2.5 text-end"><MonoValue :value="formatMoney(entry.amount)" /></td>
                <td class="px-3 py-2.5">
                  <button
                    v-if="entry.proof_url"
                    type="button"
                    class="text-bitume underline"
                    @click="previewUrl = entry.proof_url"
                  >
                    {{ t('purchasing.supplierLedger.viewProof') }}
                  </button>
                  <span v-else class="text-texte-3">—</span>
                </td>
              </tr>
              <tr v-if="ledger.entries.length === 0">
                <td colspan="5" class="text-texte-3 px-3 py-8 text-center">
                  {{ t('finance.partyLedger.noEntries') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
    </template>

    <Modal
      v-if="showPaymentForm && ledger"
      :title="t('finance.debtPayment.title')"
      max-width="max-w-2xl"
      @close="showPaymentForm = false"
    >
      <DebtPaymentForm
        initial-debt-type="supplier"
        :initial-debt-id="ledger.supplier.id"
        lock-debt-type
        lock-debt
        @success="onPaymentSaved"
        @cancel="showPaymentForm = false"
      />
    </Modal>

    <Modal
      v-if="showAdvanceForm && ledger"
      :title="t('finance.advanceForm.title')"
      max-width="max-w-2xl"
      @close="showAdvanceForm = false"
    >
      <AdvanceForm
        initial-party-type="supplier"
        :initial-party-id="ledger.supplier.id"
        lock-party-type
        lock-party
        @success="onAdvanceSaved"
        @cancel="showAdvanceForm = false"
      />
    </Modal>

    <Modal
      v-if="previewUrl"
      :title="t('purchasing.supplierLedger.table.proof')"
      max-width="max-w-3xl"
      @close="previewUrl = null"
    >
      <img :src="previewUrl" class="max-h-[80vh] w-full rounded-lg object-contain" />
      <div class="mt-4 flex justify-end">
        <Button variant="ghost" @click="previewUrl = null">{{ t('common.close') }}</Button>
      </div>
    </Modal>
  </div>
</template>
