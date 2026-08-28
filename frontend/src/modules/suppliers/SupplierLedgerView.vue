<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { fetchSupplierLedger } from '@/modules/purchasing/api'
import type { SupplierLedger } from '@/modules/purchasing/types'
import DebtPaymentForm from '@/modules/finance/DebtPaymentForm.vue'
import { formatMoney, formatQuantity } from '@/utils/currency'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Modal from '@/components/ui/Modal.vue'
import MonoValue from '@/components/ui/MonoValue.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const ledger = ref<SupplierLedger | null>(null)
const loading = ref(true)
const error = ref('')
const showPaymentForm = ref(false)
const previewUrl = ref<string | null>(null)

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

onMounted(load)

const totalReliquat = computed(
  () =>
    ledger.value?.reliquat_summary.reduce(
      (total, item) => total + Number(item.total_reliquat),
      0,
    ) ?? 0,
)
const lastPayment = computed(() => {
  const payments = [...(ledger.value?.payments ?? [])]
  return payments.sort((a, b) => b.payment_date.localeCompare(a.payment_date))[0] ?? null
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
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('purchasing.supplierLedger.title', { name: ledger?.supplier.name ?? '…' }) }}
      </h1>
      <div class="flex gap-2">
        <Button v-if="ledger" variant="primary" @click="showPaymentForm = true">
          {{ t('finance.supplierPayment.recordPayment') }}
        </Button>
        <Button variant="ghost" @click="router.push({ name: 'suppliers' })">
          {{ t('purchasing.supplierLedger.back') }}
        </Button>
      </div>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else-if="ledger">
      <section class="grid gap-3 md:grid-cols-5">
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('purchasing.supplierLedger.totalPurchased') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :value="formatMoney(ledger.total_purchased)"
          />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('purchasing.supplierLedger.totalPaid') }}
          </p>
          <MonoValue class="font-semibold" align="left" :value="formatMoney(ledger.total_paid)" />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('purchasing.supplierLedger.outstandingBalance') }}
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
            {{ t('purchasing.supplierLedger.totalReliquat') }}
          </p>
          <MonoValue class="font-semibold" align="left" :value="formatQuantity(totalReliquat)" />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('purchasing.supplierLedger.lastPayment') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :value="lastPayment ? formatMoney(lastPayment.amount) : '—'"
          />
        </div>
      </section>

      <Card :title="t('purchasing.supplierLedger.reliquatByProduct')">
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
      </Card>

      <Card :title="t('purchasing.supplierLedger.purchaseHistory')">
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
      </Card>

      <Card :title="t('purchasing.supplierLedger.paymentsAndAdvances')">
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
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="payment in ledger.payments"
              :key="payment.id"
              class="border-ligne border-b last:border-0"
            >
              <td class="px-3 py-2.5">{{ payment.payment_date }}</td>
              <td class="px-3 py-2.5">{{ t(`paymentMethod.${payment.method}`) }}</td>
              <td class="px-3 py-2.5">{{ payment.reference || '—' }}</td>
              <td class="px-3 py-2.5">
                {{ payment.is_advance ? t('common.yes') : t('common.no') }}
              </td>
              <td class="px-3 py-2.5 text-end">
                <MonoValue :value="formatMoney(payment.amount)" />
              </td>
            </tr>
            <tr v-if="ledger.payments.length === 0">
              <td colspan="5" class="text-texte-3 px-3 py-8 text-center">
                {{ t('purchasing.supplierLedger.noPayments') }}
              </td>
            </tr>
          </tbody>
        </table>
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
