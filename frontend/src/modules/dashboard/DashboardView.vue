<script setup lang="ts">
// docs/PHASE_6_PLAN.md Etape 7: 6 KPI panels (Operations, Fuel, Sales,
// Transport, Finance, Profit) backed by one aggregated backend endpoint -
// no frontend loops recomputing totals over raw records (guide Section 9.6).
//
// docs/UI_REDESIGN_PLAN.md Etape 6: layered on top, a "live ops" pulse (4
// strategic KPIs, "En route maintenant", 14-day chart, "À traiter") scoped
// to *today* rather than the DateRangeFilter below - the filter still drives
// the legacy period breakdown, but a live dashboard's headline numbers
// shouldn't silently change meaning when someone picks "This year".
// No backend endpoint was added for this: everything is derived from the
// existing dashboard summary, loss-report, trips list and customer-payments
// endpoints (see aggregate.ts for the derivations and their caveats).
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DateRangeFilter from '@/components/DateRangeFilter.vue'
import type { DateRangeValue } from '@/components/date-range'
import { fetchDashboardSummary } from './api'
import type { DashboardSummary } from './types'
import { fetchReport } from '@/modules/reports/api'
import { tripResource } from '@/modules/trips/api'
import { isTripEnRoute } from '@/modules/trips/types'
import type { Trip } from '@/modules/trips/types'
import TripCard from '@/modules/trips/TripCard.vue'
import { customerPaymentResource } from '@/modules/finance/api'
import type { CustomerPayment } from '@/modules/finance/types'
import KpiTile from './KpiTile.vue'
import VolumeTrendChart from './VolumeTrendChart.vue'
import {
  sumField,
  averageLossPercent,
  unjustifiedLosses,
  lastNDays,
  groupVolumeByDay,
  lossSeverityTone,
  type LossReportRow,
  type VolumeDay,
} from './aggregate'

const { t, locale } = useI18n()

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
    error.value = t('dashboard.errorLoad')
  } finally {
    loading.value = false
  }
}

// --- Live ops (today) --------------------------------------------------

const todayIso = new Date().toISOString().slice(0, 10)
const todayLabel = computed(() =>
  new Date().toLocaleDateString(locale.value === 'fr' ? 'fr-FR' : 'en-US', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }),
)

const liveLoading = ref(true)
const liveError = ref('')

const volumeDays = ref<VolumeDay[]>([])
const todayDelivered = ref(0)
const todayLoaded = ref(0)
const avgLossPct = ref(0)
const toTreat = ref<LossReportRow[]>([])

const trips = ref<Trip[]>([])
const enRouteTrips = computed(() => trips.value.filter((t) => isTripEnRoute(t.status)))
const blockedTrips = computed(() => trips.value.filter((t) => t.status === 'BLOCKED'))

const todayEncaissements = ref(0)
const encaissementsGauge = ref(0)

// The CustomerPayment endpoint has no ordering/date filter (only
// customer/is_indirect/method - see backend/apps/finance/views.py) and
// defaults to ascending id, so page 1 is the OLDEST payments. Recent ones
// live on the last page(s); jumping there directly (instead of walking the
// whole history) keeps this to at most 3 requests regardless of how much
// payment history exists.
async function fetchRecentCustomerPayments(): Promise<CustomerPayment[]> {
  const first = await customerPaymentResource.list()
  const pageSize = first.results.length || 25
  const totalPages = Math.max(1, Math.ceil(first.count / pageSize))
  if (totalPages === 1) return first.results
  const lastPage = await customerPaymentResource.list({ page: totalPages })
  if (totalPages === 2) return [...first.results, ...lastPage.results]
  const secondLast = await customerPaymentResource.list({ page: totalPages - 1 })
  return [...secondLast.results, ...lastPage.results]
}

async function loadLive() {
  liveLoading.value = true
  liveError.value = ''
  try {
    const days = lastNDays(14)
    const from = days[0]!.date
    const to = days[days.length - 1]!.date

    const [lossReport, tripsPage, payments] = await Promise.all([
      fetchReport('loss-report', { from, to }),
      tripResource.list(),
      fetchRecentCustomerPayments(),
    ])

    const lossRows = lossReport.rows as unknown as LossReportRow[]
    volumeDays.value = groupVolumeByDay(lossRows, days)
    const todayRows = lossRows.filter((row) => row.control_date === todayIso)
    todayDelivered.value = sumField(todayRows, 'received_quantity')
    todayLoaded.value = sumField(todayRows, 'loaded_quantity')
    avgLossPct.value = averageLossPercent(todayRows)
    toTreat.value = unjustifiedLosses(lossRows)

    trips.value = tripsPage.results

    const todayPayments = payments.filter((p) => p.payment_date === todayIso)
    const windowPayments = payments.filter((p) => p.payment_date >= from && p.payment_date <= to)
    todayEncaissements.value = todayPayments.reduce((sum, p) => sum + Number(p.amount), 0)
    const avgDaily = windowPayments.reduce((sum, p) => sum + Number(p.amount), 0) / days.length
    encaissementsGauge.value =
      avgDaily > 0
        ? Math.min(100, (todayEncaissements.value / avgDaily) * 100)
        : todayEncaissements.value > 0
          ? 100
          : 0
  } catch {
    liveError.value = t('dashboard.liveError')
  } finally {
    liveLoading.value = false
  }
}

onMounted(loadLive)

function tripIdForReference(reference: string): number | null {
  return trips.value.find((t) => t.reference === reference)?.id ?? null
}

const enRouteGauge = computed(() =>
  trips.value.length ? (enRouteTrips.value.length / trips.value.length) * 100 : 0,
)
const deliveredGauge = computed(() =>
  todayLoaded.value > 0 ? (todayDelivered.value / todayLoaded.value) * 100 : 0,
)
const lossGaugeTone = computed(() => lossSeverityTone(avgLossPct.value))
</script>

<template>
  <div class="max-w-6xl space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('dashboard.title') }}
      </h1>
      <span class="text-texte-2 font-mono text-sm capitalize">{{ todayLabel }}</span>
    </div>

    <p v-if="liveError" class="text-critique text-sm">{{ liveError }}</p>
    <p v-else-if="liveLoading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else>
      <!-- 4 KPI stratégiques -->
      <div class="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiTile
          :label="t('dashboard.kpi.deliveredToday')"
          :value="Math.round(todayDelivered).toLocaleString()"
          unit="L"
          :gauge-value="deliveredGauge"
          gauge-tone="livre"
        />
        <KpiTile
          :label="t('dashboard.kpi.tripsInProgress')"
          :value="String(enRouteTrips.length)"
          :gauge-value="enRouteGauge"
          gauge-tone="transit"
        />
        <KpiTile
          :label="t('dashboard.kpi.avgLoss')"
          :value="avgLossPct.toFixed(1)"
          unit="%"
          :gauge-value="Math.min(100, (avgLossPct / 5) * 100)"
          :gauge-tone="lossGaugeTone"
        />
        <KpiTile
          :label="t('dashboard.kpi.paymentsToday')"
          :value="Math.round(todayEncaissements).toLocaleString()"
          :gauge-value="encaissementsGauge"
          gauge-tone="livre"
        />
      </div>

      <!-- En route maintenant -->
      <section class="space-y-3">
        <h2 class="text-texte-2 text-sm font-semibold uppercase">
          {{ t('dashboard.enRouteNow', { count: enRouteTrips.length }) }}
        </h2>
        <div v-if="enRouteTrips.length" class="flex gap-3 overflow-x-auto pb-2">
          <TripCard
            v-for="trip in enRouteTrips.slice(0, 8)"
            :key="trip.id"
            :trip="trip"
            class="w-72 shrink-0"
          />
        </div>
        <p
          v-else
          class="text-texte-3 border-ligne rounded-xl border border-dashed p-6 text-center text-sm"
        >
          {{ t('dashboard.noTripsEnRoute') }}
        </p>
      </section>

      <VolumeTrendChart :days="volumeDays" />

      <!-- À traiter -->
      <section class="border-ligne rounded-xl border bg-white p-4">
        <h2 class="text-texte-2 mb-3 text-sm font-semibold uppercase">
          {{ t('dashboard.toTreat') }}
        </h2>
        <div class="grid gap-4 sm:grid-cols-2">
          <div class="space-y-2">
            <p class="text-texte-3 text-xs font-medium uppercase">
              {{ t('dashboard.unjustifiedLosses') }}
            </p>
            <ul v-if="toTreat.length" class="space-y-1.5">
              <li
                v-for="row in toTreat.slice(0, 6)"
                :key="row.trip_reference + row.control_date"
                class="bg-critique-tint flex items-center justify-between rounded-lg px-3 py-2 text-sm"
              >
                <RouterLink
                  v-if="tripIdForReference(row.trip_reference)"
                  class="text-critique-texte font-mono underline decoration-dotted"
                  :to="{
                    name: 'trip-detail',
                    params: { id: tripIdForReference(row.trip_reference)! },
                  }"
                >
                  {{ row.trip_reference }}
                </RouterLink>
                <span v-else class="text-critique-texte font-mono">{{ row.trip_reference }}</span>
                <span class="text-critique-texte font-mono tabular-nums">
                  −{{ Number(row.chargeable_loss_quantity).toLocaleString() }} L
                </span>
              </li>
            </ul>
            <p v-else class="text-texte-3 text-sm">{{ t('dashboard.noUnjustifiedLosses') }}</p>
          </div>

          <div class="space-y-2">
            <p class="text-texte-3 text-xs font-medium uppercase">
              {{ t('dashboard.urgentBlockedTrips') }}
            </p>
            <ul v-if="blockedTrips.length" class="space-y-1.5">
              <li
                v-for="trip in blockedTrips.slice(0, 6)"
                :key="trip.id"
                class="bg-critique-tint rounded-lg px-3 py-2 text-sm"
              >
                <RouterLink
                  class="text-critique-texte font-mono underline decoration-dotted"
                  :to="{ name: 'trip-detail', params: { id: trip.id } }"
                >
                  {{ trip.reference }}
                </RouterLink>
                <span class="text-critique-texte ml-2">{{ trip.truck_detail?.internal_id }}</span>
              </li>
            </ul>
            <p v-else class="text-texte-3 text-sm">{{ t('dashboard.noUrgentTrips') }}</p>
          </div>
        </div>
      </section>
    </template>

    <!-- Détail de la période sélectionnée (KPI historiques) -->
    <div class="flex flex-wrap items-center justify-between gap-3 pt-2">
      <h2 class="text-texte-2 text-sm font-semibold uppercase">
        {{ t('dashboard.periodDetail') }}
      </h2>
      <DateRangeFilter @change="load" />
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <div v-else-if="summary" class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <section class="border-ligne rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 mb-3 text-sm font-semibold uppercase">
          {{ t('dashboard.sections.operations') }}
        </h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.trips') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ summary.operations.trips_count }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.active') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ summary.operations.active_trips_count }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.delivered') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ summary.operations.delivered_trips_count }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="border-ligne rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 mb-3 text-sm font-semibold uppercase">
          {{ t('dashboard.sections.fuel') }}
        </h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.quantityLoaded') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.fuel.quantity_loaded) }} L
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.theoreticalStock') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.fuel.theoretical_stock) }} L
            </dd>
          </div>
        </dl>
      </section>

      <section class="border-ligne rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 mb-3 text-sm font-semibold uppercase">
          {{ t('dashboard.sections.sales') }}
        </h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.salesCount') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ summary.sales.sales_count }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.revenue') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.sales.revenue) }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="border-ligne rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 mb-3 text-sm font-semibold uppercase">
          {{ t('dashboard.sections.transport') }}
        </h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.settlements') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ summary.transport.settlements_count }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.transportCost') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.transport.transport_cost) }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="border-ligne rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 mb-3 text-sm font-semibold uppercase">
          {{ t('dashboard.sections.finance') }}
        </h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.expenses') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.finance.expenses_total) }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.treasuryBalance') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.finance.treasury_balance) }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="border-ligne rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 mb-3 text-sm font-semibold uppercase">
          {{ t('dashboard.sections.profit') }}
        </h3>
        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.totalMargin') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.profit.total_margin) }}
            </dd>
          </div>
        </dl>
      </section>

      <!-- Point-in-time "currently outstanding" snapshots - not affected
           by the DateRangeFilter above (see types.ts). -->
      <section class="border-ligne rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 mb-1 text-sm font-semibold uppercase">
          {{ t('dashboard.sections.debts') }}
        </h3>
        <p class="text-texte font-mono text-lg font-semibold tabular-nums">
          {{ formatNumber(summary.debts.total) }}
        </p>
        <dl class="mt-2 space-y-1 text-sm">
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.debtSuppliers') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.debts.suppliers.total) }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.debtTransporters') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.debts.transporters.total) }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.debtCustoms') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.debts.customs) }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-texte-2">{{ t('dashboard.fields.debtOther') }}</dt>
            <dd class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(summary.debts.other) }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="border-ligne rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 mb-1 text-sm font-semibold uppercase">
          {{ t('dashboard.sections.customerAmounts') }}
        </h3>
        <p class="text-texte font-mono text-lg font-semibold tabular-nums">
          {{ formatNumber(summary.customer_amounts.total) }}
        </p>
        <ul
          v-if="summary.customer_amounts.rows.length"
          class="mt-2 max-h-40 space-y-1 overflow-y-auto text-sm"
        >
          <li
            v-for="row in summary.customer_amounts.rows"
            :key="row.customer"
            class="flex justify-between"
          >
            <span class="text-texte-2">{{ row.customer }}</span>
            <span class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(row.outstanding) }}
            </span>
          </li>
        </ul>
        <p v-else class="text-texte-3 mt-2 text-sm">{{ t('dashboard.noAmounts') }}</p>
      </section>

      <section class="border-ligne rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 mb-1 text-sm font-semibold uppercase">
          {{ t('dashboard.sections.bankAmounts') }}
        </h3>
        <p class="text-texte font-mono text-lg font-semibold tabular-nums">
          {{ formatNumber(summary.bank_amounts.total) }}
        </p>
        <ul
          v-if="summary.bank_amounts.rows.length"
          class="mt-2 max-h-40 space-y-1 overflow-y-auto text-sm"
        >
          <li
            v-for="row in summary.bank_amounts.rows"
            :key="row.bank"
            class="flex justify-between"
          >
            <span class="text-texte-2">{{ row.bank }}</span>
            <span class="text-texte font-mono font-medium tabular-nums">
              {{ formatNumber(row.balance) }}
            </span>
          </li>
        </ul>
        <p v-else class="text-texte-3 mt-2 text-sm">{{ t('dashboard.noAmounts') }}</p>
      </section>
    </div>
  </div>
</template>
