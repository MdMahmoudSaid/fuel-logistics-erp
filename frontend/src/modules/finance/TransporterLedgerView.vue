<script setup lang="ts">
// docs/PHASE_5_PLAN.md Etape 8/10: gross fees earned, loss deductions,
// advances consumed and what's already settled for one transporter
// (guide Section 1.5/8.6: "earned - deductions - advances - payments =
// transporter outstanding"), backed by GET /api/transporters/{id}/ledger/.
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchTransporterLedger } from './api'
import type { TransporterLedger } from './types'

const route = useRoute()
const router = useRouter()

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
    error.value = 'Could not load the transporter ledger.'
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
        Transporter Ledger — {{ ledger?.transporter.name ?? '…' }}
      </h2>
      <button
        class="px-3 py-2 text-sm text-slate-500"
        @click="router.push({ name: 'transporters' })"
      >
        Back
      </button>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">Loading…</p>

    <template v-else-if="ledger">
      <section class="grid grid-cols-5 gap-3">
        <div class="rounded border bg-white p-3">
          <p class="text-xs text-slate-500">Gross earned</p>
          <p class="text-base font-semibold text-slate-800">
            {{ Number(ledger.gross_amount).toLocaleString() }}
          </p>
        </div>
        <div class="rounded border bg-white p-3">
          <p class="text-xs text-slate-500">Deductions</p>
          <p class="text-base font-semibold text-red-600">
            − {{ Number(ledger.deductions).toLocaleString() }}
          </p>
        </div>
        <div class="rounded border bg-white p-3">
          <p class="text-xs text-slate-500">Advances applied</p>
          <p class="text-base font-semibold text-red-600">
            − {{ Number(ledger.advances_applied).toLocaleString() }}
          </p>
        </div>
        <div class="rounded border bg-white p-3">
          <p class="text-xs text-slate-500">Already settled</p>
          <p class="text-base font-semibold text-slate-800">
            {{ Number(ledger.settled).toLocaleString() }}
          </p>
        </div>
        <div class="rounded border bg-white p-3">
          <p class="text-xs text-slate-500">Net outstanding</p>
          <p
            class="text-base font-semibold"
            :class="Number(ledger.net_outstanding) > 0 ? 'text-amber-600' : 'text-emerald-600'"
          >
            {{ Number(ledger.net_outstanding).toLocaleString() }}
          </p>
        </div>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-base font-semibold text-slate-800">Settlements by trip</h3>
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-b text-slate-500">
              <th class="px-2 py-1.5 font-medium">Trip</th>
              <th class="px-2 py-1.5 font-medium text-right">Base</th>
              <th class="px-2 py-1.5 font-medium text-right">Deduction</th>
              <th class="px-2 py-1.5 font-medium text-right">Net</th>
              <th class="px-2 py-1.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="payment in ledger.payments" :key="payment.id" class="border-b last:border-0">
              <td class="px-2 py-1.5 font-medium text-slate-800">{{ payment.trip_reference }}</td>
              <td class="px-2 py-1.5 text-right">
                {{ Number(payment.base_amount).toLocaleString() }}
              </td>
              <td class="px-2 py-1.5 text-right text-red-600">
                − {{ Number(payment.deduction_amount).toLocaleString() }}
              </td>
              <td class="px-2 py-1.5 text-right font-medium text-slate-800">
                {{ Number(payment.net_amount).toLocaleString() }}
              </td>
              <td class="px-2 py-1.5">
                <span
                  class="rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="STATUS_BADGE[payment.status]"
                >
                  {{ payment.status }}
                </span>
              </td>
            </tr>
            <tr v-if="ledger.payments.length === 0">
              <td colspan="5" class="px-2 py-4 text-center text-slate-400">No settlements yet.</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-base font-semibold text-slate-800">Advances</h3>
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-b text-slate-500">
              <th class="px-2 py-1.5 font-medium">Date</th>
              <th class="px-2 py-1.5 font-medium">Reference</th>
              <th class="px-2 py-1.5 font-medium">Settled</th>
              <th class="px-2 py-1.5 font-medium text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="advance in ledger.advances" :key="advance.id" class="border-b last:border-0">
              <td class="px-2 py-1.5">{{ advance.date }}</td>
              <td class="px-2 py-1.5">{{ advance.reference || '—' }}</td>
              <td class="px-2 py-1.5">{{ advance.settled ? 'Yes' : 'No' }}</td>
              <td class="px-2 py-1.5 text-right font-medium text-slate-800">
                {{ Number(advance.amount).toLocaleString() }}
              </td>
            </tr>
            <tr v-if="ledger.advances.length === 0">
              <td colspan="4" class="px-2 py-4 text-center text-slate-400">No advances yet.</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
