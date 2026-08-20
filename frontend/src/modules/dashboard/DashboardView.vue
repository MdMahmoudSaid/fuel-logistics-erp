<script setup lang="ts">
// docs/PHASE_6_PLAN.md Etape 7: 6 KPI panels (Operations, Fuel, Sales,
// Transport, Finance, Profit) backed by one aggregated backend endpoint -
// no frontend loops recomputing totals over raw records (guide Section 9.6).
import { ref } from 'vue'
import DateRangeFilter from '@/components/DateRangeFilter.vue'
import type { DateRangeValue } from '@/components/date-range'
import { fetchDashboardSummary } from './api'
import type { DashboardSummary } from './types'

const summary = ref<DashboardSummary | null>(null)
const loading = ref(true)
const error = ref('')

function formatNumber(value: string | number): string {
  return Number(value).toLocaleString()
}

async function load(filter: DateRangeValue) {
  loading.value = true
  error.value = ''
  try {
    summary.value = await fetchDashboardSummary(filter as Record<string, string | undefined>)
  } catch {
    error.value = 'Could not load the dashboard.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="max-w-6xl space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="text-lg font-semibold text-slate-800">Dashboard</h2>
      <DateRangeFilter @change="load" />
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">Loading…</p>

    <div v-else-if="summary" class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-sm font-semibold text-slate-500">Operations</h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-slate-500">Trips</dt>
            <dd class="font-medium text-slate-800">{{ summary.operations.trips_count }}</dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-slate-500">Active</dt>
            <dd class="font-medium text-slate-800">{{ summary.operations.active_trips_count }}</dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-slate-500">Delivered</dt>
            <dd class="font-medium text-slate-800">
              {{ summary.operations.delivered_trips_count }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-sm font-semibold text-slate-500">Fuel</h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-slate-500">Quantity loaded</dt>
            <dd class="font-medium text-slate-800">
              {{ formatNumber(summary.fuel.quantity_loaded) }} L
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-slate-500">Theoretical stock</dt>
            <dd class="font-medium text-slate-800">
              {{ formatNumber(summary.fuel.theoretical_stock) }} L
            </dd>
          </div>
        </dl>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-sm font-semibold text-slate-500">Sales</h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-slate-500">Sales</dt>
            <dd class="font-medium text-slate-800">{{ summary.sales.sales_count }}</dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-slate-500">Revenue</dt>
            <dd class="font-medium text-slate-800">{{ formatNumber(summary.sales.revenue) }}</dd>
          </div>
        </dl>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-sm font-semibold text-slate-500">Transport</h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-slate-500">Settlements</dt>
            <dd class="font-medium text-slate-800">{{ summary.transport.settlements_count }}</dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-slate-500">Transport cost</dt>
            <dd class="font-medium text-slate-800">
              {{ formatNumber(summary.transport.transport_cost) }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-sm font-semibold text-slate-500">Finance</h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-slate-500">Expenses</dt>
            <dd class="font-medium text-slate-800">
              {{ formatNumber(summary.finance.expenses_total) }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-slate-500">Treasury balance</dt>
            <dd class="font-medium text-slate-800">
              {{ formatNumber(summary.finance.treasury_balance) }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="rounded border bg-white p-4">
        <h3 class="mb-3 text-sm font-semibold text-slate-500">Profit</h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-slate-500">Total margin</dt>
            <dd class="font-medium text-slate-800">
              {{ formatNumber(summary.profit.total_margin) }}
            </dd>
          </div>
        </dl>
      </section>
    </div>
  </div>
</template>
