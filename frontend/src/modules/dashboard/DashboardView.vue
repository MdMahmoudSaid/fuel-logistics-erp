<script setup lang="ts">
// docs/PHASE_6_PLAN.md Etape 7: 6 KPI panels (Operations, Fuel, Sales,
// Transport, Finance, Profit) backed by one aggregated backend endpoint -
// no frontend loops recomputing totals over raw records (guide Section 9.6).
//
// docs/UI_REDESIGN_PLAN.md Etape 6: layered on top, a "live ops" pulse (4
// strategic KPIs, "En route maintenant") scoped to *today* rather than the
// DateRangeFilter below - the filter still drives
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
import { customerPaymentResource } from '@/modules/finance/api'
import type { CustomerPayment } from '@/modules/finance/types'
import KpiTile from './KpiTile.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import Icon from '@/components/ui/Icon.vue'
import type { IconName } from '@/components/ui/Icon.vue'
import { formatMoney, formatMoneyParts, formatQuantityParts } from '@/utils/currency'
import {
  sumField,
  averageLossPercent,
  lastNDays,
  lossSeverityTone,
  type LossReportRow,
} from './aggregate'

const { t, locale } = useI18n()

const summary = ref<DashboardSummary | null>(null)
const loading = ref(true)
const error = ref('')
// Dashboard recette fix (2026-09-04): remembered so the 4 top KPI cards can
// carry the currently-selected period along as query params when navigating
// away - the target pages (Depenses generales, Benefices) don't consume
// them yet (neither has a period-filter query-param contract today), but
// passing them now is forward-compatible and harmless.
const currentPeriod = ref<DateRangeValue>({})

async function load(filter: DateRangeValue) {
  loading.value = true
  error.value = ''
  currentPeriod.value = filter
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
const dateLocale = computed(() => {
  if (locale.value === 'fr') return 'fr-FR'
  if (locale.value === 'ar') return 'ar'
  return 'en-US'
})
const todayLabel = computed(() =>
  new Date().toLocaleDateString(dateLocale.value, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }),
)

const liveLoading = ref(true)
const liveError = ref('')

const todayDelivered = ref(0)
const todayLoaded = ref(0)
const avgLossPct = ref(0)

const trips = ref<Trip[]>([])
const enRouteTrips = computed(() => trips.value.filter((t) => isTripEnRoute(t.status)))

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
    const todayRows = lossRows.filter((row) => row.control_date === todayIso)
    todayDelivered.value = sumField(todayRows, 'received_quantity')
    todayLoaded.value = sumField(todayRows, 'loaded_quantity')
    avgLossPct.value = averageLossPercent(todayRows)

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

const enRouteGauge = computed(() =>
  trips.value.length ? (enRouteTrips.value.length / trips.value.length) * 100 : 0,
)
const deliveredGauge = computed(() =>
  todayLoaded.value > 0 ? (todayDelivered.value / todayLoaded.value) * 100 : 0,
)
const lossGaugeTone = computed(() => lossSeverityTone(avgLossPct.value))

// Dashboard recette fix (2026-09-04): the currently-selected period, passed
// through as query params on each card's navigation target - see
// currentPeriod's own comment for why the target pages don't consume it yet.
const periodQuery = computed(() => {
  const p = currentPeriod.value as Record<string, string | undefined>
  const query: Record<string, string> = {}
  for (const key of ['preset', 'range', 'start_date', 'end_date', 'from', 'to']) {
    if (p[key]) query[key] = p[key]!
  }
  return query
})

const financialCards = computed(() => {
  if (!summary.value) return []
  const s = summary.value.financial_summary
  return [
    {
      labelKey: 'dashboard.final.periodRevenue',
      raw: s.period_revenue,
      tone: 'neutral',
      icon: 'trending-up' as IconName,
      // Client instruction (2026-09-04): no dedicated "trajets comptabilises"
      // route exists yet - page Benefices is the most natural existing
      // destination for revenue detail.
      to: { name: 'profit', query: periodQuery.value },
    },
    {
      labelKey: 'dashboard.final.periodCollections',
      raw: s.period_collections,
      tone: 'positive',
      icon: 'wallet' as IconName,
      // TreasuryLedgerView's typeFilter ref already supports 'in'/'out'/
      // 'transfer' via a simple <select> - reading it from ?type= on
      // mount (see that component) is the "simple existing filter" the
      // instruction asked for.
      to: { name: 'treasury-transactions', query: { type: 'in', ...periodQuery.value } },
    },
    {
      labelKey: 'dashboard.final.periodPaidExpenses',
      raw: s.period_paid_expenses,
      tone: 'neutral',
      icon: 'receipt' as IconName,
      to: { name: 'expenses', query: periodQuery.value },
    },
    {
      labelKey: 'dashboard.final.periodNetProfit',
      raw: s.period_net_profit,
      tone: Number(s.period_net_profit) >= 0 ? 'positive' : 'negative',
      icon: 'coins' as IconName,
      to: { name: 'profit', query: periodQuery.value },
    },
  ].map((card) => ({
    label: t(card.labelKey),
    amountParts: formatMoneyParts(card.raw),
    negative: Number(card.raw) < 0,
    tone: card.tone,
    icon: card.icon,
    to: card.to,
  }))
})

const treasuryCard = computed(() => {
  if (!summary.value) return null
  const balance = summary.value.financial_summary.current_treasury_balance
  return {
    amountParts: formatMoneyParts(balance),
    bankParts: formatMoneyParts(summary.value.bank_amounts.total),
    cashParts: formatMoneyParts(summary.value.cash_amounts.total),
    negative: Number(balance) < 0,
  }
})

const workingCapitalCard = computed(() => {
  if (!summary.value) return null
  const wc = summary.value.working_capital
  return {
    // Client modifications (2026-09-04, third pass - confirmed bug during
    // actual recette testing): headline figure is tresorerie + creances +
    // dettes ouvertes, ADDED - brut and the debt buckets are shown as
    // distinct rows below, purely informational (they already sum into
    // the headline, never subtracted from it).
    totalParts: formatMoneyParts(wc.total),
    negative: Number(wc.total) < 0,
    grossParts: formatMoneyParts(wc.gross),
    capitalParts: formatMoneyParts(wc.capital),
    treasuryParts: formatMoneyParts(wc.treasury_available),
    receivablesParts: formatMoneyParts(wc.customer_receivables),
    supplierParts: formatMoneyParts(wc.supplier_debt_total),
    transporterParts: formatMoneyParts(wc.transporter_debt_total),
    otherDebtsParts: formatMoneyParts(wc.other_debts),
  }
})

const partyCards = computed(() => {
  if (!summary.value) return []
  const p = summary.value.party_balances

  function partySub(balance: string) {
    const value = Number(balance)
    if (value < 0) return t('dashboard.final.debtToPay')
    if (value > 0) return t('dashboard.final.advanceAvailable')
    return t('dashboard.final.noOpenBalance')
  }

  return [
    {
      label: t('dashboard.final.customers'),
      to: { name: 'customers' },
      balance: p.customers.balance,
      detail: t('dashboard.final.openCustomers', { count: p.customers.open_count }),
      sub: p.customers.largest_open
        ? t('dashboard.final.largestCustomerDebt', { name: p.customers.largest_open.name })
        : t('dashboard.final.nothingToSettle'),
      icon: 'users' as IconName,
      negative: false,
    },
    {
      label: t('dashboard.final.suppliers'),
      to: { name: 'suppliers' },
      balance: p.suppliers.balance,
      detail: t('dashboard.final.openSuppliers', { count: p.suppliers.open_count }),
      sub: partySub(p.suppliers.balance),
      icon: 'package' as IconName,
      negative: false,
    },
    {
      label: t('dashboard.final.transporters'),
      to: { name: 'transporters' },
      balance: p.transporters.balance,
      detail: t('dashboard.final.openTransporters', { count: p.transporters.open_count }),
      sub: partySub(p.transporters.balance),
      icon: 'truck' as IconName,
      negative: false,
    },
    {
      label: t('dashboard.final.shareholders'),
      to: { name: 'shareholders' },
      balance: p.shareholders.balance,
      detail: t('dashboard.final.withdrawn', {
        amount: formatMoney(p.shareholders.total_withdrawn),
      }),
      sub: t('dashboard.final.openLoans', { amount: formatMoney(p.shareholders.open_loans_total) }),
      icon: 'pie-chart' as IconName,
      negative: false,
    },
    {
      label: t('dashboard.final.customsAndOther'),
      to: { name: 'treasury-transactions' },
      balance: p.customs_and_other.balance,
      detail: t('dashboard.final.customs', { amount: formatMoney(p.customs_and_other.customs) }),
      sub: t('dashboard.final.roadTransit', {
        amount: formatMoney(p.customs_and_other.road_transit),
      }),
      icon: 'shield' as IconName,
      negative: false,
    },
  ].map((card) => ({
    ...card,
    balanceParts: formatMoneyParts(card.balance),
  }))
})

const quickActions: {
  labelKey: string
  icon: IconName
  to: { name: string; query?: Record<string, string> }
}[] = [
  {
    labelKey: 'dashboard.quickActions.newSupplierOrder',
    icon: 'cart-plus',
    to: { name: 'supplier-order-new' },
  },
  {
    labelKey: 'dashboard.quickActions.newCessionLetter',
    icon: 'file-signature',
    to: { name: 'cession-letter-new' },
  },
  { labelKey: 'dashboard.quickActions.newTrip', icon: 'route', to: { name: 'trip-new' } },
  {
    labelKey: 'dashboard.quickActions.newCustomerPayment',
    icon: 'credit-card',
    to: { name: 'invoices', query: { action: 'payment' } },
  },
  {
    labelKey: 'dashboard.quickActions.newPayment',
    icon: 'banknote',
    to: { name: 'treasury-transactions', query: { action: 'payment' } },
  },
]

const stockTotalParts = computed(() =>
  summary.value
    ? formatQuantityParts(summary.value.company_stock.total_quantity)
    : { value: '0', unit: 'L' },
)

const compactEnRouteTrips = computed(() => enRouteTrips.value.slice(0, 5))
</script>

<template>
  <div class="w-full space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('dashboard.title') }}
      </h1>
      <span class="text-texte-2 font-mono text-sm capitalize">{{ todayLabel }}</span>
    </div>

    <div class="flex justify-end">
      <DateRangeFilter @change="load" />
    </div>

    <template v-if="summary">
      <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <RouterLink
          v-for="card in financialCards"
          :key="card.label"
          :to="card.to"
          data-test="financial-kpi-card"
          class="financial-kpi-card border-ligne hover:border-transit hover:bg-fond-2 focus-visible:ring-transit block rounded-lg border bg-white p-4 transition-colors focus-visible:ring-2 focus-visible:outline-none"
        >
          <div class="flex items-center gap-2">
            <span
              class="bg-transit-tint text-transit inline-flex size-7 shrink-0 items-center justify-center rounded-lg"
            >
              <Icon :name="card.icon" :size="16" />
            </span>
            <p class="financial-kpi-label text-texte-2 text-xs font-semibold uppercase">
              {{ card.label }}
            </p>
          </div>
          <p
            class="financial-kpi-amount mt-2 text-xl font-semibold"
            :class="[
              card.negative
                ? 'text-critique'
                : card.tone === 'positive'
                  ? 'text-livre-texte'
                  : card.tone === 'info'
                    ? 'text-transit-texte'
                    : 'text-texte',
            ]"
          >
            <MonoValue v-bind="card.amountParts" align="left" />
          </p>
        </RouterLink>
      </section>

      <section class="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
        <section
          data-test="action-items"
          class="border-ligne relative rounded-lg border bg-white p-4 shadow-sm before:absolute before:inset-y-4 before:start-0 before:w-1 before:rounded-e-full before:bg-orange"
        >
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 class="text-texte flex items-center gap-2 text-sm font-semibold uppercase">
              <span
                class="bg-orange-tint text-orange-fonce inline-flex size-8 shrink-0 items-center justify-center rounded-lg"
              >
                <Icon name="route" :size="16" />
              </span>
              {{ t('dashboard.toTreat') }}
            </h2>
            <span
              data-test="action-count-badge"
              class="bg-orange-tint text-orange-fonce inline-flex h-7 min-w-7 items-center justify-center rounded-full px-2 font-mono text-sm font-semibold tabular-nums"
            >
              {{ summary.action_items.length }}
            </span>
          </div>
          <ul v-if="summary.action_items.length" class="grid gap-2 md:grid-cols-2">
            <li v-for="item in summary.action_items" :key="item.kind + item.object_id">
              <RouterLink
                :to="{ name: 'trip-detail', params: { id: item.object_id } }"
                class="border-ligne text-texte hover:border-orange hover:bg-white flex min-h-12 items-center justify-between gap-3 rounded-lg border bg-sable px-3 py-2 text-sm transition"
              >
                <span class="line-clamp-2">{{ item.label }}</span>
                <span class="shrink-0 font-mono tabular-nums">{{ item.reference }}</span>
              </RouterLink>
            </li>
          </ul>
          <p v-else class="text-texte-2 text-sm">{{ t('dashboard.noUrgentTrips') }}</p>
        </section>

        <div class="space-y-4">
          <section class="treasury-card border-ligne rounded-lg border bg-white p-4">
            <div class="flex items-center gap-2">
              <span
                class="bg-transit-tint text-transit-texte inline-flex size-8 shrink-0 items-center justify-center rounded-lg"
              >
                <Icon name="landmark" :size="16" />
              </span>
              <h2 class="text-texte-2 text-sm font-semibold uppercase">
                {{ t('dashboard.final.availableTreasury') }}
              </h2>
            </div>
            <p
              v-if="treasuryCard"
              class="treasury-amount mt-3 text-2xl font-semibold"
              :class="treasuryCard.negative ? 'text-critique' : 'text-texte'"
            >
              <MonoValue v-bind="treasuryCard.amountParts" align="left" />
            </p>
            <dl v-if="treasuryCard" class="mt-4 grid gap-2 text-sm">
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.banks') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="treasuryCard.bankParts" />
                </dd>
              </div>
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.cashAccounts') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="treasuryCard.cashParts" />
                </dd>
              </div>
            </dl>
          </section>

          <section class="working-capital-card border-ligne rounded-lg border bg-white p-4">
            <div class="flex items-center gap-2">
              <span
                class="bg-transit-tint text-transit-texte inline-flex size-8 shrink-0 items-center justify-center rounded-lg"
              >
                <Icon name="landmark" :size="16" />
              </span>
              <h2 class="text-texte-2 text-sm font-semibold uppercase">
                {{ t('dashboard.final.workingCapital') }}
              </h2>
            </div>
            <p class="text-texte-3 mt-1 text-xs">{{ t('dashboard.final.workingCapitalHelp') }}</p>
            <p
              v-if="workingCapitalCard"
              class="mt-3 text-2xl font-semibold"
              :class="workingCapitalCard.negative ? 'text-critique' : 'text-texte'"
            >
              <MonoValue v-bind="workingCapitalCard.totalParts" align="left" />
            </p>
            <dl v-if="workingCapitalCard" class="mt-4 grid gap-2 text-sm">
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.workingCapitalGross') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.grossParts" />
                </dd>
              </div>
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.capitalContributed') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.capitalParts" />
                </dd>
              </div>
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.availableTreasury') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.treasuryParts" />
                </dd>
              </div>
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.customerReceivables') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.receivablesParts" />
                </dd>
              </div>
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.supplierDebtTotal') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.supplierParts" />
                </dd>
              </div>
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.transporterDebtTotal') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.transporterParts" />
                </dd>
              </div>
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.otherDebts') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.otherDebtsParts" />
                </dd>
              </div>
            </dl>
          </section>
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-texte-2 text-sm font-semibold uppercase">
          {{ t('dashboard.final.partyBalances') }}
        </h2>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <RouterLink
            v-for="card in partyCards"
            :key="card.label"
            :to="card.to"
            data-test="party-balance-card"
            class="party-balance-card border-ligne hover:border-orange focus-visible:outline-orange rounded-lg border bg-white p-4 transition hover:-translate-y-0.5 hover:shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <div class="flex items-center gap-2">
              <span
                class="bg-ecart-tint text-ecart-texte inline-flex size-7 shrink-0 items-center justify-center rounded-lg"
              >
                <Icon :name="card.icon" :size="16" />
              </span>
              <p class="text-texte-2 min-h-8 text-xs font-semibold uppercase">{{ card.label }}</p>
            </div>
            <p
              data-test="party-balance-amount"
              class="party-balance-amount mt-2 text-lg font-semibold"
              :class="card.negative ? 'text-critique' : 'text-texte'"
            >
              <MonoValue v-bind="card.balanceParts" align="left" />
            </p>
            <p class="text-texte-2 mt-2 text-sm">{{ card.detail }}</p>
            <p class="text-texte-3 mt-1 text-xs">{{ card.sub }}</p>
          </RouterLink>
        </div>
      </section>

      <section class="border-ligne rounded-lg border bg-white p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="text-texte-2 flex items-center gap-2 text-sm font-semibold uppercase">
              <span
                class="bg-livre-tint text-livre-texte inline-flex size-7 shrink-0 items-center justify-center rounded-lg"
              >
                <Icon name="droplet" :size="16" />
              </span>
              {{ t('dashboard.final.companyStock') }}
            </h2>
            <p class="text-texte mt-2 text-2xl font-semibold">
              <MonoValue v-bind="stockTotalParts" align="left" />
            </p>
            <p class="text-texte-2 text-sm">
              {{
                t('dashboard.final.companyStockTrips', {
                  count: summary.company_stock.trips_count,
                })
              }}
            </p>
          </div>
          <RouterLink
            :to="{ name: 'company-stock' }"
            class="border-ligne-forte text-texte hover:bg-sable inline-flex h-9 shrink-0 items-center rounded-lg border px-3 text-sm font-medium transition"
          >
            {{ t('dashboard.viewDetails') }}
          </RouterLink>
        </div>
        <div class="mt-4 grid gap-2 md:grid-cols-3">
          <div
            v-for="row in summary.company_stock.by_product"
            :key="row.product"
            class="bg-sable rounded-lg px-3 py-2"
          >
            <span class="text-texte-2 text-sm">{{ row.product }}</span>
            <span class="text-texte ms-2 font-medium">
              <MonoValue v-bind="formatQuantityParts(row.quantity)" />
            </span>
          </div>
        </div>
      </section>
    </template>

    <p v-if="liveError" class="text-critique text-sm">{{ liveError }}</p>
    <p v-else-if="liveLoading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else>
      <!-- 4 KPI stratégiques -->
      <div class="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiTile
          :label="t('dashboard.kpi.deliveredToday')"
          :value="formatQuantityParts(Math.round(todayDelivered)).value"
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
          :value="formatMoneyParts(Math.round(todayEncaissements)).value"
          unit="XOF"
          :gauge-value="encaissementsGauge"
          gauge-tone="livre"
        />
      </div>

      <!-- En route maintenant -->
      <section data-test="en-route-compact" class="border-ligne rounded-lg border bg-white p-4">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 class="text-texte-2 text-sm font-semibold uppercase">
            {{ t('dashboard.enRouteNow', { count: enRouteTrips.length }) }}
          </h2>
          <RouterLink
            :to="{ name: 'trips' }"
            class="border-ligne-forte text-texte hover:bg-sable inline-flex h-8 shrink-0 items-center rounded-lg border px-3 text-sm font-medium transition"
          >
            {{ t('dashboard.viewAll') }}
          </RouterLink>
        </div>
        <div v-if="enRouteTrips.length" class="overflow-x-auto">
          <table class="min-w-full text-sm">
            <tbody class="divide-ligne divide-y">
              <tr v-for="trip in compactEnRouteTrips" :key="trip.id">
                <td class="py-2 pe-3">
                  <RouterLink
                    :to="{ name: 'trip-detail', params: { id: trip.id } }"
                    class="text-texte hover:text-orange-fonce font-mono font-semibold tabular-nums"
                  >
                    {{ trip.reference }}
                  </RouterLink>
                </td>
                <td class="text-texte-2 px-3 py-2">
                  {{ trip.truck_detail?.internal_id ?? '—' }}
                </td>
                <td class="text-texte-2 px-3 py-2">
                  {{ trip.transporter_detail?.name ?? '—' }}
                </td>
                <td class="py-2 ps-3 text-end">
                  <MonoValue v-bind="formatQuantityParts(trip.quantity_loaded)" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p
          v-else
          class="text-texte-3 border-ligne rounded-lg border border-dashed p-4 text-center text-sm"
        >
          {{ t('dashboard.noTripsEnRoute') }}
        </p>
      </section>

      <!-- Actions rapides -->
      <section class="space-y-3">
        <h2 class="text-texte-2 text-sm font-semibold uppercase">
          {{ t('dashboard.quickActions.title') }}
        </h2>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <RouterLink
            v-for="action in quickActions"
            :key="action.labelKey"
            :to="action.to"
            class="border-ligne hover:border-bitume hover:bg-sable flex flex-col items-center gap-2 rounded-lg border bg-white p-4 text-center transition"
          >
            <span
              class="bg-orange-tint text-orange-fonce inline-flex size-9 items-center justify-center rounded-lg"
            >
              <Icon :name="action.icon" :size="18" />
            </span>
            <span class="text-texte text-xs font-medium">{{ t(action.labelKey) }}</span>
          </RouterLink>
        </div>
      </section>
    </template>

    <details data-test="period-detail" class="border-ligne rounded-lg border bg-white p-4">
      <summary class="text-texte-2 cursor-pointer text-sm font-semibold uppercase">
        {{ t('dashboard.periodDetail') }}
      </summary>

      <p v-if="error" class="text-critique mt-4 text-sm">{{ error }}</p>
      <p v-else-if="loading" class="text-texte-3 mt-4 text-sm">{{ t('common.loading') }}</p>

      <div v-else-if="summary" class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatQuantityParts(summary.fuel.quantity_loaded)" />
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.theoreticalStock') }}</dt>
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatQuantityParts(summary.fuel.theoretical_stock)" />
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
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(summary.sales.revenue)" />
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
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(summary.transport.transport_cost)" />
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
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(summary.finance.expenses_total)" />
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.treasuryBalance') }}</dt>
              <dd
                class="font-medium"
                :class="
                  Number(summary.finance.treasury_balance) < 0 ? 'text-critique' : 'text-texte'
                "
              >
                <MonoValue v-bind="formatMoneyParts(summary.finance.treasury_balance)" />
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
              <dd
                class="font-medium"
                :class="Number(summary.profit.total_margin) < 0 ? 'text-critique' : 'text-texte'"
              >
                <MonoValue v-bind="formatMoneyParts(summary.profit.total_margin)" />
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
          <p class="text-texte text-lg font-semibold">
            <MonoValue v-bind="formatMoneyParts(summary.debts.total)" />
          </p>
          <dl class="mt-2 space-y-1 text-sm">
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.debtSuppliers') }}</dt>
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(summary.debts.suppliers.total)" />
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.debtTransporters') }}</dt>
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(summary.debts.transporters.total)" />
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.debtCustoms') }}</dt>
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(summary.debts.customs)" />
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.debtTransit') }}</dt>
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(summary.debts.transit)" />
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.debtRoadTransit') }}</dt>
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(summary.debts.road_transit)" />
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.debtOther') }}</dt>
              <dd class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(summary.debts.other)" />
              </dd>
            </div>
          </dl>
        </section>

        <section class="border-ligne rounded-xl border bg-white p-4">
          <h3 class="text-texte-2 mb-1 text-sm font-semibold uppercase">
            {{ t('dashboard.sections.customerAmounts') }}
          </h3>
          <p class="text-texte text-lg font-semibold">
            <MonoValue v-bind="formatMoneyParts(summary.customer_amounts.total)" />
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
              <span class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(row.outstanding)" />
              </span>
            </li>
          </ul>
          <p v-else class="text-texte-3 mt-2 text-sm">{{ t('dashboard.noAmounts') }}</p>
        </section>

        <section class="border-ligne rounded-xl border bg-white p-4">
          <h3 class="text-texte-2 mb-1 text-sm font-semibold uppercase">
            {{ t('dashboard.sections.bankAmounts') }}
          </h3>
          <p class="text-texte text-lg font-semibold">
            <MonoValue v-bind="formatMoneyParts(summary.bank_amounts.total)" />
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
              <span class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(row.balance)" />
              </span>
            </li>
          </ul>
          <p v-else class="text-texte-3 mt-2 text-sm">{{ t('dashboard.noAmounts') }}</p>
        </section>

        <section class="border-ligne rounded-xl border bg-white p-4">
          <h3 class="text-texte-2 mb-1 text-sm font-semibold uppercase">
            {{ t('dashboard.sections.cashAmounts') }}
          </h3>
          <p class="text-texte text-lg font-semibold">
            <MonoValue v-bind="formatMoneyParts(summary.cash_amounts.total)" />
          </p>
          <ul
            v-if="summary.cash_amounts.rows.length"
            class="mt-2 max-h-40 space-y-1 overflow-y-auto text-sm"
          >
            <li
              v-for="row in summary.cash_amounts.rows"
              :key="row.cash_account"
              class="flex justify-between"
            >
              <span class="text-texte-2">{{ row.cash_account }}</span>
              <span class="text-texte font-medium">
                <MonoValue v-bind="formatMoneyParts(row.balance)" />
              </span>
            </li>
          </ul>
          <p v-else class="text-texte-3 mt-2 text-sm">{{ t('dashboard.noAmounts') }}</p>
        </section>

        <!-- Summary only (design doc 2026-08-26-benefices-associes-
           refinement-design.md) - the Benefices page (/profit) stays the
           single detailed source, this never breaks it down per trip or
           per shareholder. Point-in-time, not scoped by the date range. -->
        <section class="border-ligne rounded-xl border bg-white p-4">
          <div class="mb-1 flex items-center justify-between">
            <h3 class="text-texte-2 text-sm font-semibold uppercase">
              {{ t('dashboard.sections.shareholders') }}
            </h3>
            <RouterLink
              :to="{ name: 'profit' }"
              class="border-ligne-forte text-texte hover:bg-sable inline-flex h-7 shrink-0 items-center rounded-lg border px-2.5 text-xs font-medium transition"
            >
              {{ t('dashboard.viewDetails') }}
            </RouterLink>
          </div>
          <p class="text-texte text-lg font-semibold">
            <MonoValue v-bind="formatMoneyParts(summary.shareholders_summary.current_profit)" />
          </p>
          <dl class="mt-2 space-y-1 text-sm">
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.shareholdersWithdrawn') }}</dt>
              <dd class="text-texte font-medium">
                <MonoValue
                  v-bind="formatMoneyParts(summary.shareholders_summary.total_withdrawn)"
                />
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.shareholdersRemaining') }}</dt>
              <dd class="text-texte font-medium">
                <MonoValue
                  v-bind="formatMoneyParts(summary.shareholders_summary.remaining_undistributed)"
                />
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-texte-2">{{ t('dashboard.fields.shareholdersOpenLoans') }}</dt>
              <dd class="text-texte font-medium">
                <MonoValue
                  v-bind="formatMoneyParts(summary.shareholders_summary.open_loans_total)"
                />
              </dd>
            </div>
            <div class="border-ligne flex justify-between border-t pt-1">
              <dt class="text-texte-2">
                {{ t('dashboard.fields.shareholdersDistributableResult') }}
              </dt>
              <dd class="text-texte font-medium">
                <MonoValue
                  v-bind="formatMoneyParts(summary.shareholders_summary.distributable_result)"
                />
              </dd>
            </div>
          </dl>
        </section>
      </div>
    </details>
  </div>
</template>

<style scoped>
.financial-kpi-card {
  min-height: 112px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.financial-kpi-label {
  min-height: 2rem;
}

.financial-kpi-amount {
  min-height: 2rem;
  display: flex;
  align-items: baseline;
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
  white-space: nowrap;
}

.treasury-card {
  min-height: 168px;
}

.treasury-amount,
.party-balance-amount {
  display: flex;
  align-items: baseline;
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
  min-height: 2rem;
  white-space: nowrap;
}

.party-balance-card {
  min-height: 172px;
  display: flex;
  flex-direction: column;
}

.party-balance-card p:last-child {
  margin-top: auto;
}
</style>
