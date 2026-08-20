<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { fetchSupplierLedger } from '@/modules/purchasing/api'
import type { SupplierLedger } from '@/modules/purchasing/types'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const ledger = ref<SupplierLedger | null>(null)
const loading = ref(true)
const error = ref('')

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

onMounted(load)

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-slate-100 text-slate-600',
  CONFIRMED: 'bg-emerald-100 text-emerald-700',
  CANCELLED: 'bg-red-100 text-red-700',
}
</script>

<template>
  <div class="max-w-4xl space-y-6">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">
        {{ t('purchasing.supplierLedger.title', { name: ledger?.supplier.name ?? '…' }) }}
      </h2>
      <button class="px-3 py-2 text-sm text-slate-500" @click="router.push({ name: 'suppliers' })">
        {{ t('purchasing.supplierLedger.back') }}
      </button>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">{{ t('common.loading') }}</p>

    <template v-else-if="ledger">
      <section class="grid grid-cols-3 gap-4">
        <div class="rounded border bg-white p-4">
          <p class="text-xs text-slate-500">{{ t('purchasing.supplierLedger.totalPurchased') }}</p>
          <p class="text-lg font-semibold text-slate-800">
            {{ Number(ledger.total_purchased).toLocaleString() }}
          </p>
        </div>
        <div class="rounded border bg-white p-4">
          <p class="text-xs text-slate-500">{{ t('purchasing.supplierLedger.totalPaid') }}</p>
          <p class="text-lg font-semibold text-slate-800">
            {{ Number(ledger.total_paid).toLocaleString() }}
          </p>
        </div>
        <div class="rounded border bg-white p-4">
          <p class="text-xs text-slate-500">
            {{ t('purchasing.supplierLedger.outstandingBalance') }}
          </p>
          <p
            class="text-lg font-semibold"
            :class="Number(ledger.outstanding_balance) > 0 ? 'text-amber-600' : 'text-emerald-600'"
          >
            {{ Number(ledger.outstanding_balance).toLocaleString() }}
          </p>
        </div>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-base font-semibold text-slate-800">
          {{ t('purchasing.supplierLedger.reliquatByProduct') }}
        </h3>
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-b text-slate-500">
              <th class="px-2 py-1.5 font-medium">{{ t('purchasing.supplierLedger.product') }}</th>
              <th class="px-2 py-1.5 font-medium text-right">
                {{ t('purchasing.supplierLedger.totalReliquat') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in ledger.reliquat_summary"
              :key="item.product_id"
              class="border-b last:border-0"
            >
              <td class="px-2 py-1.5">{{ item.product_name }}</td>
              <td
                class="px-2 py-1.5 text-right font-medium"
                :class="Number(item.total_reliquat) <= 0 ? 'text-red-600' : 'text-slate-800'"
              >
                {{ Number(item.total_reliquat).toLocaleString() }}
              </td>
            </tr>
            <tr v-if="ledger.reliquat_summary.length === 0">
              <td colspan="2" class="px-2 py-4 text-center text-slate-400">
                {{ t('purchasing.supplierLedger.noPurchaseHistory') }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-base font-semibold text-slate-800">
          {{ t('purchasing.supplierLedger.purchaseHistory') }}
        </h3>
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-b text-slate-500">
              <th class="px-2 py-1.5 font-medium">{{ t('purchasing.supplierLedger.table.reference') }}</th>
              <th class="px-2 py-1.5 font-medium">{{ t('purchasing.supplierLedger.table.product') }}</th>
              <th class="px-2 py-1.5 font-medium">{{ t('purchasing.supplierLedger.table.date') }}</th>
              <th class="px-2 py-1.5 font-medium text-right">
                {{ t('purchasing.supplierLedger.table.purchased') }}
              </th>
              <th class="px-2 py-1.5 font-medium text-right">
                {{ t('purchasing.supplierLedger.table.reliquat') }}
              </th>
              <th class="px-2 py-1.5 font-medium">{{ t('purchasing.supplierLedger.table.status') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="order in ledger.orders"
              :key="order.id"
              class="cursor-pointer border-b last:border-0 hover:bg-slate-50"
              @click="router.push({ name: 'supplier-order-detail', params: { id: order.id } })"
            >
              <td class="px-2 py-1.5 font-medium text-slate-800">{{ order.reference }}</td>
              <td class="px-2 py-1.5">{{ order.product_detail?.name }}</td>
              <td class="px-2 py-1.5">{{ order.purchase_date }}</td>
              <td class="px-2 py-1.5 text-right">
                {{ Number(order.quantity_litres).toLocaleString() }}
              </td>
              <td
                class="px-2 py-1.5 text-right font-medium"
                :class="Number(order.reliquat) <= 0 ? 'text-red-600' : 'text-slate-800'"
              >
                {{ Number(order.reliquat).toLocaleString() }}
              </td>
              <td class="px-2 py-1.5">
                <span
                  class="rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="STATUS_BADGE[order.status]"
                >
                  {{ t(`supplierOrderStatus.${order.status}`) }}
                </span>
              </td>
            </tr>
            <tr v-if="ledger.orders.length === 0">
              <td colspan="6" class="px-2 py-4 text-center text-slate-400">
                {{ t('purchasing.supplierLedger.noPurchaseHistory') }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-base font-semibold text-slate-800">
          {{ t('purchasing.supplierLedger.paymentsAndAdvances') }}
        </h3>
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-b text-slate-500">
              <th class="px-2 py-1.5 font-medium">{{ t('purchasing.supplierLedger.paymentsTable.date') }}</th>
              <th class="px-2 py-1.5 font-medium">
                {{ t('purchasing.supplierLedger.paymentsTable.method') }}
              </th>
              <th class="px-2 py-1.5 font-medium">
                {{ t('purchasing.supplierLedger.paymentsTable.reference') }}
              </th>
              <th class="px-2 py-1.5 font-medium">
                {{ t('purchasing.supplierLedger.paymentsTable.advance') }}
              </th>
              <th class="px-2 py-1.5 font-medium text-right">
                {{ t('purchasing.supplierLedger.paymentsTable.amount') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="payment in ledger.payments" :key="payment.id" class="border-b last:border-0">
              <td class="px-2 py-1.5">{{ payment.payment_date }}</td>
              <td class="px-2 py-1.5">{{ t(`paymentMethod.${payment.method}`) }}</td>
              <td class="px-2 py-1.5">{{ payment.reference || '—' }}</td>
              <td class="px-2 py-1.5">{{ payment.is_advance ? t('common.yes') : t('common.no') }}</td>
              <td class="px-2 py-1.5 text-right font-medium text-slate-800">
                {{ Number(payment.amount).toLocaleString() }}
              </td>
            </tr>
            <tr v-if="ledger.payments.length === 0">
              <td colspan="5" class="px-2 py-4 text-center text-slate-400">
                {{ t('purchasing.supplierLedger.noPayments') }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
