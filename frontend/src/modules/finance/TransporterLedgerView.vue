<script setup lang="ts">
// docs/PHASE_5_PLAN.md Etape 8/10: gross fees earned, loss deductions,
// advances consumed and what's already settled for one transporter
// (guide Section 1.5/8.6: "earned - deductions - advances - payments =
// transporter outstanding"), backed by GET /api/transporters/{id}/ledger/.
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { fetchTransporterLedger } from './api'
import type { TransporterLedger } from './types'
import { formatMoney } from '@/utils/currency'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const ledger = ref<TransporterLedger | null>(null)
const loading = ref(true)
const error = ref('')

const transporterId = computed(() => Number(route.params.id))

async function load() {
  loading.value = true
  error.value = ''
  try {
    ledger.value = await fetchTransporterLedger(transporterId.value)
  } catch {
    error.value = t('finance.transporterLedger.loadError')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const STATUS_BADGE: Record<string, string> = {
  PLANNED: 'bg-slate-100 text-slate-600',
  PAYABLE: 'bg-amber-100 text-amber-700',
  PARTIALLY_PAID: 'bg-amber-100 text-amber-700',
  PAID: 'bg-emerald-100 text-emerald-700',
  DEDUCTION_APPLIED: 'bg-sky-100 text-sky-700',
}
</script>

<template>
  <div class="max-w-4xl space-y-6">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">
        {{ t('finance.transporterLedger.title', { name: ledger?.transporter.name ?? '…' }) }}
      </h2>
      <button
        class="px-3 py-2 text-sm text-slate-500"
        @click="router.push({ name: 'transporters' })"
      >
        {{ t('finance.transporterLedger.back') }}
      </button>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">{{ t('common.loading') }}</p>

    <template v-else-if="ledger">
      <section class="grid grid-cols-5 gap-3">
        <div class="rounded border bg-white p-3">
          <p class="text-xs text-slate-500">{{ t('finance.transporterLedger.grossEarned') }}</p>
          <p class="text-base font-semibold text-slate-800">
            {{ formatMoney(ledger.gross_amount) }}
          </p>
        </div>
        <div class="rounded border bg-white p-3">
          <p class="text-xs text-slate-500">{{ t('finance.transporterLedger.deductions') }}</p>
          <p class="text-base font-semibold text-red-600">
            − {{ formatMoney(ledger.deductions) }}
          </p>
        </div>
        <div class="rounded border bg-white p-3">
          <p class="text-xs text-slate-500">{{ t('finance.transporterLedger.advancesApplied') }}</p>
          <p class="text-base font-semibold text-red-600">
            − {{ formatMoney(ledger.advances_applied) }}
          </p>
        </div>
        <div class="rounded border bg-white p-3">
          <p class="text-xs text-slate-500">{{ t('finance.transporterLedger.alreadySettled') }}</p>
          <p class="text-base font-semibold text-slate-800">
            {{ formatMoney(ledger.settled) }}
          </p>
        </div>
        <div class="rounded border bg-white p-3">
          <p class="text-xs text-slate-500">{{ t('finance.transporterLedger.netOutstanding') }}</p>
          <p
            class="text-base font-semibold"
            :class="Number(ledger.net_outstanding) > 0 ? 'text-amber-600' : 'text-emerald-600'"
          >
            {{ formatMoney(ledger.net_outstanding) }}
          </p>
        </div>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-base font-semibold text-slate-800">
          {{ t('finance.transporterLedger.settlementsByTrip') }}
        </h3>
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-b text-slate-500">
              <th class="px-2 py-1.5 font-medium">{{ t('finance.transporterLedger.table.trip') }}</th>
              <th class="px-2 py-1.5 font-medium text-right">
                {{ t('finance.transporterLedger.table.base') }}
              </th>
              <th class="px-2 py-1.5 font-medium text-right">
                {{ t('finance.transporterLedger.table.deduction') }}
              </th>
              <th class="px-2 py-1.5 font-medium text-right">
                {{ t('finance.transporterLedger.table.net') }}
              </th>
              <th class="px-2 py-1.5 font-medium">
                {{ t('finance.transporterLedger.table.status') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="payment in ledger.payments" :key="payment.id" class="border-b last:border-0">
              <td class="px-2 py-1.5 font-medium text-slate-800">{{ payment.trip_reference }}</td>
              <td class="px-2 py-1.5 text-right">
                {{ formatMoney(payment.base_amount) }}
              </td>
              <td class="px-2 py-1.5 text-right text-red-600">
                − {{ formatMoney(payment.deduction_amount) }}
              </td>
              <td class="px-2 py-1.5 text-right font-medium text-slate-800">
                {{ formatMoney(payment.net_amount) }}
              </td>
              <td class="px-2 py-1.5">
                <span
                  class="rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="STATUS_BADGE[payment.status]"
                >
                  {{ t(`settlementStatus.${payment.status}`) }}
                </span>
              </td>
            </tr>
            <tr v-if="ledger.payments.length === 0">
              <td colspan="5" class="px-2 py-4 text-center text-slate-400">
                {{ t('finance.transporterLedger.noSettlements') }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-base font-semibold text-slate-800">
          {{ t('finance.transporterLedger.advances') }}
        </h3>
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-b text-slate-500">
              <th class="px-2 py-1.5 font-medium">
                {{ t('finance.transporterLedger.advancesTable.date') }}
              </th>
              <th class="px-2 py-1.5 font-medium">
                {{ t('finance.transporterLedger.advancesTable.reference') }}
              </th>
              <th class="px-2 py-1.5 font-medium">
                {{ t('finance.transporterLedger.advancesTable.settled') }}
              </th>
              <th class="px-2 py-1.5 font-medium text-right">
                {{ t('finance.transporterLedger.advancesTable.amount') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="advance in ledger.advances" :key="advance.id" class="border-b last:border-0">
              <td class="px-2 py-1.5">{{ advance.date }}</td>
              <td class="px-2 py-1.5">{{ advance.reference || '—' }}</td>
              <td class="px-2 py-1.5">{{ advance.settled ? t('common.yes') : t('common.no') }}</td>
              <td class="px-2 py-1.5 text-right font-medium text-slate-800">
                {{ formatMoney(advance.amount) }}
              </td>
            </tr>
            <tr v-if="ledger.advances.length === 0">
              <td colspan="4" class="px-2 py-4 text-center text-slate-400">
                {{ t('finance.transporterLedger.noAdvances') }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
