<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// Financial figures follow the selected period; live operations remain scoped to today.
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DateRangeFilter from '@/components/DateRangeFilter.vue'
import type { DateRangeValue } from '@/components/date-range'
import { fetchDashboardSummary, downloadWorkingCapitalPdf } from './api'
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
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
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

// Fond de roulement breakdown is collapsed by default (client request 2026-09-24).
const workingCapitalOpen = ref(false)

// PDF of the card with a custom choice of lines (client request 2026-09-25).
// Keys match backend WORKING_CAPITAL_LINES; the labels are the card's own.
const WC_PDF_LINES = [
  { key: 'total', label: 'dashboard.final.workingCapital' },
  { key: 'capital', label: 'dashboard.final.capitalContributed' },
  { key: 'treasury', label: 'dashboard.final.availableTreasury' },
  { key: 'receivables', label: 'dashboard.final.customerReceivables' },
  { key: 'supplier_debt', label: 'dashboard.final.supplierDebtTotal' },
  { key: 'transporter_debt', label: 'dashboard.final.transporterDebtTotal' },
  { key: 'other_debts', label: 'dashboard.final.otherDebts' },
  { key: 'shareholder_dues', label: 'dashboard.final.shareholderDues' },
  { key: 'supplier_company_stock', label: 'dashboard.final.supplierCompanyStockValue' },
  { key: 'supplier_in_transit', label: 'dashboard.final.supplierInTransitValue' },
  { key: 'supplier_reliquat', label: 'dashboard.final.supplierReliquatValue' },
] as const
const wcPdfOpen = ref(false)
const wcPdfSelected = ref<string[]>(WC_PDF_LINES.map((line) => line.key))
const wcPdfLoading = ref(false)
const wcPdfError = ref('')

function openWcPdf() {
  wcPdfSelected.value = WC_PDF_LINES.map((line) => line.key)
  wcPdfError.value = ''
  wcPdfOpen.value = true
}
async function onDownloadWcPdf() {
  wcPdfLoading.value = true
  wcPdfError.value = ''
  try {
    await downloadWorkingCapitalPdf(wcPdfSelected.value, locale.value)
    wcPdfOpen.value = false
  } catch {
    wcPdfError.value = t('dashboard.final.wcPdf.error')
  } finally {
    wcPdfLoading.value = false
  }
}

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
    capitalParts: formatMoneyParts(wc.capital),
    treasuryParts: formatMoneyParts(wc.treasury_available),
    receivablesParts: formatMoneyParts(wc.customer_receivables),
    supplierParts: formatMoneyParts(wc.supplier_debt_total),
    transporterParts: formatMoneyParts(wc.transporter_debt_total),
    otherDebtsParts: formatMoneyParts(wc.other_debts),
    shareholderDuesParts: formatMoneyParts(wc.shareholder_dues ?? '0'),
    supplierReliquatParts: formatMoneyParts(wc.supplier_reliquat_value),
    supplierInTransitParts: formatMoneyParts(wc.supplier_in_transit_value),
    supplierCompanyStockParts: formatMoneyParts(wc.supplier_company_stock_value),
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
      label: t('dashboard.final.customsAndOther'),
      to: { name: 'treasury-transactions' },
      balance: p.customs_and_other.balance,
      // Bug fix (recette manuelle 2026-09-06): this card's total was
      // always the sum of all 4 buckets (customs + transit + road_transit
      // + other), but the itemization below only ever showed 2 of them -
      // "transit" and "other" existed in the API response and were simply
      // never read here.
      detail:
        t('dashboard.final.customs', { amount: formatMoney(p.customs_and_other.customs) }) +
        ' · ' +
        t('dashboard.final.transit', { amount: formatMoney(p.customs_and_other.transit) }),
      sub:
        t('dashboard.final.roadTransit', {
          amount: formatMoney(p.customs_and_other.road_transit),
        }) +
        ' · ' +
        t('dashboard.final.other', { amount: formatMoney(p.customs_and_other.other) }),
      icon: 'shield' as IconName,
      negative: false,
    },
  ].map((card) => ({
    ...card,
    balanceParts: formatMoneyParts(card.balance),
  }))
})

// Client request (2026-09-06): "where does every purchased litre sit right
// now" - reliquat chez le fournisseur -> en cours (chargé, pas arrivé) ->
// stock entreprise (arrivé), in that order so the row itself tells the
// supply-chain story. A trip delivered to a client leaves all three (it's
// a customer receivable at that point, shown elsewhere) - the backend
// already excludes it, this only ever renders what it's given.
//
// Dynamic by request: a stage with nothing in it (quantity 0) is dropped
// entirely rather than shown as a dead "0" tile - flex (not a fixed-column
// grid) so the remaining 1 or 2 cards share the row evenly instead of
// leaving empty gaps where the hidden ones would have been.
const pipelineCards = computed(() => {
  if (!summary.value) return []
  const p = summary.value
  return [
    {
      key: 'supplier_reliquat',
      label: t('dashboard.pipeline.supplierReliquat'),
      to: { name: 'suppliers' },
      icon: 'package' as IconName,
      quantity: p.supplier_reliquat.quantity,
      value: p.supplier_reliquat.value,
    },
    {
      key: 'in_transit',
      label: t('dashboard.pipeline.inTransit'),
      to: { name: 'trips' },
      icon: 'truck' as IconName,
      quantity: p.in_transit.quantity,
      value: p.in_transit.value,
    },
    {
      key: 'company_stock',
      label: t('dashboard.pipeline.companyStock'),
      to: { name: 'company-stock' },
      icon: 'droplet' as IconName,
      quantity: p.company_stock.total_quantity,
      value: p.company_stock.value,
    },
  ]
    .filter((card) => Number(card.quantity) > 0)
    .map((card) => ({
      ...card,
      quantityParts: formatQuantityParts(card.quantity),
      valueParts: formatMoneyParts(card.value),
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

    <AppAlert v-if="error" :message="error" />
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

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

      <section v-if="pipelineCards.length" class="flex flex-col gap-3 sm:flex-row">
        <RouterLink
          v-for="card in pipelineCards"
          :key="card.key"
          :to="card.to"
          data-test="pipeline-card"
          class="pipeline-card border-ligne hover:border-livre hover:bg-fond-2 focus-visible:ring-livre block flex-1 rounded-lg border bg-white p-4 transition-colors focus-visible:ring-2 focus-visible:outline-none"
        >
          <div class="flex items-center gap-2">
            <span
              class="bg-livre-tint text-livre-texte inline-flex size-7 shrink-0 items-center justify-center rounded-lg"
            >
              <Icon :name="card.icon" :size="16" />
            </span>
            <p class="text-texte-2 text-xs font-semibold uppercase">{{ card.label }}</p>
          </div>
          <p class="mt-2 text-lg font-semibold">
            <MonoValue v-bind="card.valueParts" align="left" />
          </p>
          <p class="text-texte-2 mt-1 text-sm">
            <MonoValue v-bind="card.quantityParts" align="left" />
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
            <div v-if="workingCapitalCard" class="mt-3 flex items-center gap-2">
              <p
                class="text-2xl font-semibold"
                :class="workingCapitalCard.negative ? 'text-critique' : 'text-texte'"
              >
                <MonoValue v-bind="workingCapitalCard.totalParts" align="left" />
              </p>
              <button
                type="button"
                data-test="working-capital-toggle"
                class="text-texte-3 hover:text-texte hover:bg-sable focus-visible:ring-transit inline-flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors focus-visible:ring-2 focus-visible:outline-none"
                :aria-expanded="workingCapitalOpen"
                aria-controls="working-capital-detail"
                :aria-label="
                  workingCapitalOpen
                    ? t('dashboard.final.hideDetail')
                    : t('dashboard.final.showDetail')
                "
                @click="workingCapitalOpen = !workingCapitalOpen"
              >
                <Icon :name="workingCapitalOpen ? 'eye-off' : 'eye'" :size="18" />
              </button>
              <button
                type="button"
                data-test="working-capital-pdf"
                class="text-texte-3 hover:text-texte hover:bg-sable focus-visible:ring-transit inline-flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors focus-visible:ring-2 focus-visible:outline-none"
                :aria-label="t('dashboard.final.wcPdf.open')"
                :title="t('dashboard.final.wcPdf.open')"
                @click="openWcPdf"
              >
                <Icon name="download" :size="18" />
              </button>
            </div>
            <dl
              v-if="workingCapitalCard && workingCapitalOpen"
              id="working-capital-detail"
              data-test="working-capital-detail"
              class="mt-4 grid gap-2 text-sm"
            >
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
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.shareholderDues') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.shareholderDuesParts" />
                </dd>
              </div>
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.supplierCompanyStockValue') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.supplierCompanyStockParts" />
                </dd>
              </div>
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.supplierInTransitValue') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.supplierInTransitParts" />
                </dd>
              </div>
              <div class="bg-sable flex items-center justify-between gap-3 rounded-lg px-3 py-2">
                <dt class="text-texte-2">{{ t('dashboard.final.supplierReliquatValue') }}</dt>
                <dd class="text-texte font-medium">
                  <MonoValue v-bind="workingCapitalCard.supplierReliquatParts" />
                </dd>
              </div>
            </dl>
            <Modal
              v-if="wcPdfOpen"
              :title="t('dashboard.final.wcPdf.title')"
              @close="wcPdfOpen = false"
            >
              <div class="space-y-3" data-test="working-capital-pdf-modal">
                <p class="text-texte-2 text-sm">{{ t('dashboard.final.wcPdf.hint') }}</p>
                <label
                  v-for="line in WC_PDF_LINES"
                  :key="line.key"
                  class="bg-sable flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm"
                >
                  <input v-model="wcPdfSelected" type="checkbox" :value="line.key" />
                  <span class="text-texte">{{ t(line.label) }}</span>
                </label>
                <p v-if="wcPdfError" class="text-critique text-sm">{{ wcPdfError }}</p>
                <div class="flex justify-end gap-2">
                  <Button type="button" variant="ghost" @click="wcPdfOpen = false">
                    {{ t('common.cancel') }}
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    data-test="working-capital-pdf-download"
                    :disabled="!wcPdfSelected.length"
                    :loading="wcPdfLoading"
                    @click="onDownloadWcPdf"
                  >
                    {{ t('dashboard.final.wcPdf.download') }}
                  </Button>
                </div>
              </div>
            </Modal>
          </section>
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-texte-2 text-sm font-semibold uppercase">
          {{ t('dashboard.final.partyBalances') }}
        </h2>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
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

    <AppAlert v-if="liveError" :message="liveError" />
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
          <ul class="divide-ligne divide-y text-sm">
            <li
              v-for="trip in compactEnRouteTrips"
              :key="trip.id"
              class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2"
            >
              <RouterLink
                :to="{ name: 'trip-detail', params: { id: trip.id } }"
                class="text-texte hover:text-orange-fonce font-mono font-semibold tabular-nums"
              >
                {{ trip.reference }}
              </RouterLink>
              <MonoValue class="sm:order-last" v-bind="formatQuantityParts(trip.quantity_loaded)" />
              <span class="text-texte-2 w-full min-w-0 sm:w-auto sm:flex-1">
                {{ trip.truck_detail?.internal_id ?? '—' }} ·
                {{ trip.transporter_detail?.name ?? '—' }}
              </span>
            </li>
          </ul>
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
