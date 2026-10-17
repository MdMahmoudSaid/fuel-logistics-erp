<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// "Benefices" page (design doc 2026-08-26-benefices-associes-refinement-
// design.md; docs/finances_edit.md) - lives in Tresorerie & Finance, but
// reuses the existing profit engine end to end: GET /api/reports/
// margin-report/ (backend/apps/reports/queries/margin_report.py's
// MarginReportQuery, itself delegating to TripProfitService) for the
// per-trip breakdown, and the same profit-preview endpoint the
// Actionnaires/Associes page uses for the live "current profit" figure.
// Nothing here recomputes a cost or margin formula - CA/supplier-cost
// totals below are trivial quantity x price sums, not business
// invariants.
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import DateRangeFilter from '@/components/DateRangeFilter.vue'
import type { DateRangeValue } from '@/components/date-range'
import { fetchReport } from '@/modules/reports/api'
import { exportProfitReportPdf, fetchShareholderProfitPreview } from './api'
import type { ShareholderProfitPreview } from './types'
import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import ManualProfitSection from './ManualProfitSection.vue'
import { useAuthStore } from '@/stores/auth'
import type { IconName } from '@/components/ui/Icon.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { formatMoney, formatQuantity, formatUnitMoney } from '@/utils/currency'

const { t, locale } = useI18n()
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role_detail?.name === 'Admin')
const manualProfits = ref<InstanceType<typeof ManualProfitSection> | null>(null)

interface MarginRow {
  // Since-closure delta row ("Periode en cours", spec 2026-10-05-periodes-
  // independantes): additive columns hold the change, not the trip total.
  is_adjustment: boolean
  revenue: string
  supplier_cost: string
  trip_reference: string
  client: string
  product: string
  quantity: string
  quantity_loaded: string
  quantity_invoiced: string
  transporter_loss_quantity: string
  transporter_loss_indemnity: string
  supplier_unit_price: string
  transport_cost: string
  customs_cost: string
  transit_cost: string
  road_transit_cost: string
  border_cost: string
  loading_cost: string
  additional_costs: string
  real_total_cost: string
  unit_cost: string
  unit_selling_price: string
  unit_profit: string
  current_margin: string
}

const dateRange = ref<DateRangeValue>({})
const rows = ref<MarginRow[]>([])
const loadingRows = ref(false)
const loadingPreview = ref(false)
// loadRows() and loadPreview() run in parallel but resolve at different
// speeds - gating the page on loadingRows alone let the operational-profit
// card (fed by rows) render before the preview arrived, flashing the
// general-expenses/net-profit cards next to it blank for a moment.
const loading = computed(() => loadingRows.value || loadingPreview.value)
const error = ref('')
const preview = ref<ShareholderProfitPreview | null>(null)

function num(value: string): number {
  return Number(value)
}

// Client modifications (2026-09-04, third pass): "dettes ouvertes" step
// between brut and the final FDR figure - the same 3 debt buckets
// working_capital.total already adds, summed here purely for display (not
// recomputed/renamed anywhere in working_capital itself).
const workingCapitalDebtsTotal = computed(() => {
  if (!preview.value) return 0
  const wc = preview.value.working_capital
  return num(wc.supplier_debt_total) + num(wc.transporter_debt_total) + num(wc.other_debts)
})

const periodProfit = computed(() => rows.value.reduce((sum, r) => sum + num(r.current_margin), 0))
// Each row carries its own revenue/supplier cost: a quantity x price
// product would be wrong on an adjustment row, which only holds deltas.
const revenue = computed(() => rows.value.reduce((sum, r) => sum + num(r.revenue), 0))
const supplierCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.supplier_cost), 0))
const lossIndemnity = computed(() =>
  rows.value.reduce((sum, r) => sum + num(r.transporter_loss_indemnity), 0),
)
const transportCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.transport_cost), 0))
const customsCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.customs_cost), 0))
const transitCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.transit_cost), 0))
// Bug fix (2026-09-03 recette manuelle): road_transit_cost ("Transit
// routiere") used to have no dedicated card and was silently folded into
// additional_costs - it now gets its own card, same as transit/border/
// loading below.
const roadTransitCost = computed(() =>
  rows.value.reduce((sum, r) => sum + num(r.road_transit_cost), 0),
)
const borderCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.border_cost), 0))
const loadingCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.loading_cost), 0))
const otherCosts = computed(() => rows.value.reduce((sum, r) => sum + num(r.additional_costs), 0))
const costs = computed(() => [
  { key: 'supplierCost', value: supplierCost.value, icon: 'fuel' as IconName },
  { key: 'transportCost', value: transportCost.value, icon: 'truck' as IconName },
  { key: 'lossIndemnity', value: lossIndemnity.value, icon: 'circle-dollar-sign' as IconName },
  { key: 'customsCost', value: customsCost.value, icon: 'landmark' as IconName },
  { key: 'transitCost', value: transitCost.value, icon: 'route' as IconName },
  { key: 'roadTransitCost', value: roadTransitCost.value, icon: 'route' as IconName },
  { key: 'borderCost', value: borderCost.value, icon: 'shield-check' as IconName },
  { key: 'loadingCost', value: loadingCost.value, icon: 'package' as IconName },
  { key: 'otherCosts', value: otherCosts.value, icon: 'file-text' as IconName },
])

const periodProfitTone = computed(() =>
  periodProfit.value < 0 ? 'text-critique' : periodProfit.value > 0 ? 'text-livre' : 'text-texte',
)

async function loadRows() {
  loadingRows.value = true
  error.value = ''
  try {
    const params: Record<string, string | undefined> = { ...dateRange.value }
    const report = await fetchReport('margin-report', params)
    rows.value = report.rows as unknown as MarginRow[]
  } catch {
    error.value = t('finance.profit.loadError')
    rows.value = []
  } finally {
    loadingRows.value = false
  }
}

async function loadPreview(params: Record<string, string | undefined>) {
  loadingPreview.value = true
  try {
    preview.value = await fetchShareholderProfitPreview(params)
  } catch {
    preview.value = null
  } finally {
    loadingPreview.value = false
  }
}

function reload() {
  loadRows()
  loadPreview({ ...dateRange.value })
}

function onDateRangeChange(value: DateRangeValue) {
  dateRange.value = value
  const params: Record<string, string | undefined> = { ...value }
  loadRows()
  loadPreview(params)
}

// Client request (2026-09-06): "Exporter en PDF" on the Benefices page -
// a real structured document (server-rendered), never a screenshot of
// this page, respecting the same period filter currently applied here.
const exportingPdf = ref(false)
const exportError = ref('')

async function onExportPdf() {
  exportingPdf.value = true
  exportError.value = ''
  try {
    await exportProfitReportPdf({ ...dateRange.value }, locale.value)
  } catch {
    exportError.value = t('reports.exportError')
  } finally {
    exportingPdf.value = false
  }
}
</script>

<template>
  <div class="max-w-6xl space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('finance.profit.title') }}
      </h1>
      <div class="flex flex-wrap items-center gap-2">
        <Button
          v-if="isAdmin && !loading"
          variant="primary"
          data-test="profit-add-manual"
          @click="manualProfits?.openAdd()"
        >
          {{ t('finance.profit.added.add') }}
        </Button>
        <Button
          v-if="!loading"
          variant="ghost"
          :disabled="exportingPdf"
          data-test="profit-export-pdf"
          @click="onExportPdf"
        >
          {{ t('reports.exportPdf') }}
        </Button>
      </div>
    </div>

    <div class="border-ligne flex flex-wrap items-end gap-3 rounded-xl border bg-white p-4">
      <DateRangeFilter @change="onDateRangeChange" />
    </div>

    <AppAlert v-if="exportError" :message="exportError" />
    <AppAlert v-if="error" :message="error" />
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else>
      <!-- Section 1: Rentabilite - "Est-ce que l'activite est rentable ?"
           Operational profit (trips only), general expenses actually paid,
           and net profit after those expenses - all sourced from the same
           period-scoped preview, never recomputed here. Revenue/trip count
           are folded into the operational card as compact sub-values
           rather than a separate card (UI simplification, 2026-09-04). -->
      <section>
        <h2 class="text-texte font-display text-lg font-semibold uppercase">
          {{ t('finance.profit.sections.profitability') }}
        </h2>
        <p class="text-texte-3 mb-3 text-sm">
          {{ t('finance.profit.sections.profitabilityQuestion') }}
        </p>
        <div class="grid gap-3 lg:grid-cols-3">
          <div
            data-test="profit-operational-card"
            class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
          >
            <div class="text-texte flex items-center gap-2">
              <span
                class="bg-livre-tint text-livre-texte inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
              >
                <Icon name="trending-up" :size="18" />
              </span>
              <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
                {{ t('finance.profit.operationalProfit') }}
              </p>
            </div>
            <MonoValue
              class="mt-2 text-2xl font-semibold"
              :class="periodProfitTone"
              align="left"
              :value="formatMoney(periodProfit)"
            />
            <div class="border-ligne mt-3 grid gap-2 border-t pt-3 sm:grid-cols-2">
              <div>
                <p class="text-texte-2 text-xs font-medium uppercase">
                  {{ t('finance.profit.revenue') }}
                </p>
                <MonoValue align="left" :value="formatMoney(revenue)" />
              </div>
              <div>
                <p class="text-texte-2 text-xs font-medium uppercase">
                  {{ t('finance.profit.tripsCount') }}
                </p>
                <MonoValue align="left" :value="String(rows.length)" />
              </div>
            </div>
          </div>
          <div
            data-test="profit-net-card"
            class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
          >
            <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
              {{ t('finance.profit.generalExpensesPaid') }}
            </p>
            <MonoValue
              v-if="preview"
              class="mt-2 text-lg font-semibold"
              align="left"
              :value="formatMoney(preview.general_expenses_paid)"
            />
          </div>
          <div
            data-test="profit-net-card"
            class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
          >
            <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
              {{ t('finance.profit.netProfit') }}
            </p>
            <MonoValue
              v-if="preview"
              class="mt-2 text-lg font-semibold"
              :class="Number(preview.net_profit) < 0 ? 'text-critique' : 'text-livre'"
              align="left"
              :value="formatMoney(preview.net_profit)"
            />
            <!-- Reconciliation with the cards to the left (spec 2026-10-05):
                 a deficit left by the last closure, and distributions
                 validated/cancelled since it. -->
            <p
              v-if="preview && Number(preview.carried_over) < 0"
              data-test="profit-carried-over"
              class="text-texte-3 mt-2 text-xs"
            >
              {{ t('finance.profit.carriedOver') }} :
              <span class="text-critique font-mono">{{ formatMoney(preview.carried_over) }}</span>
            </p>
            <p
              v-if="preview && Number(preview.brought_forward_profit ?? 0) > 0"
              data-test="profit-brought-forward"
              class="text-texte-3 mt-1 text-xs"
            >
              {{ t('finance.profit.broughtForward') }} :
              <span class="text-livre font-mono">{{
                formatMoney(preview.brought_forward_profit ?? 0)
              }}</span>
            </p>
            <p
              v-if="preview && Number(preview.manual_profit ?? 0) > 0"
              data-test="profit-manual"
              class="text-texte-3 mt-1 text-xs"
            >
              {{ t('finance.profit.manualProfit') }} :
              <span class="text-livre font-mono">{{
                formatMoney(preview.manual_profit ?? 0)
              }}</span>
            </p>
            <p
              v-if="preview && Math.abs(Number(preview.distributions_since_closure)) > 0"
              data-test="profit-distributions-since-closure"
              class="text-texte-3 mt-1 text-xs"
            >
              {{ t('finance.profit.distributionsSinceClosure') }} :
              <span class="font-mono">{{
                formatMoney(-Number(preview.distributions_since_closure))
              }}</span>
            </p>
          </div>
        </div>
      </section>

      <ManualProfitSection ref="manualProfits" @changed="reload" />

      <!-- Section 2: Distribution - "Combien peut-on distribuer aux
           associes ?" Client modifications (2026-09-04, third pass):
           brut -> dettes ouvertes -> capital apporte -> resultat
           distribuable, all sourced from the same preview, never
           recomputed here, informational only - the real distribution
           form lives on the Actionnaires/Associes page. -->
      <section v-if="preview">
        <h2 class="text-texte font-display text-lg font-semibold uppercase">
          {{ t('finance.profit.sections.distribution') }}
        </h2>
        <p class="text-texte-3 mb-3 text-sm">
          {{ t('finance.profit.sections.distributionQuestion') }}
        </p>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div
            data-test="profit-working-capital-gross-card"
            class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
          >
            <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
              {{ t('finance.profit.workingCapitalGross') }}
            </p>
            <MonoValue
              class="mt-2 text-lg font-semibold"
              align="left"
              :value="formatMoney(preview.working_capital.gross)"
            />
          </div>
          <div
            data-test="profit-working-capital-debts-card"
            class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
          >
            <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
              {{ t('finance.profit.workingCapitalDebts') }}
            </p>
            <MonoValue
              class="mt-2 text-lg font-semibold"
              align="left"
              :value="formatMoney(workingCapitalDebtsTotal)"
            />
          </div>
          <div
            data-test="profit-capital-card"
            class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
          >
            <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
              {{ t('finance.profit.capitalContributed') }}
            </p>
            <MonoValue
              class="mt-2 text-lg font-semibold"
              align="left"
              :value="formatMoney(preview.working_capital.capital)"
            />
          </div>
          <div
            data-test="profit-already-distributed-card"
            class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
          >
            <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
              {{ t('finance.profit.alreadyDistributed') }}
            </p>
            <MonoValue
              class="mt-2 text-lg font-semibold"
              align="left"
              :value="formatMoney(preview.already_distributed)"
            />
          </div>
          <div
            data-test="profit-distributable-result-card"
            class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
          >
            <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
              {{ t('finance.profit.distributableResult') }}
            </p>
            <MonoValue
              class="mt-2 text-lg font-semibold"
              :class="Number(preview.distributable_result) < 0 ? 'text-critique' : 'text-livre'"
              align="left"
              :value="formatMoney(preview.distributable_result)"
            />
            <p class="text-texte-3 mt-1 text-xs">
              {{ t('finance.profit.distributableResultHelp') }}
            </p>
          </div>
        </div>
      </section>

      <!-- Section 3: Detail des couts trajets - collapsed by default
           (native <details>, no extra dependency), pushed to the bottom -
           these are the cost-basis components already inside
           real_total_cost/operational profit above, shown here only for
           transparency, never a separate figure. -->
      <details class="border-ligne rounded-xl border bg-white">
        <summary class="text-texte cursor-pointer p-4 font-display text-lg font-semibold uppercase">
          {{ t('finance.profit.sections.costDetail') }}
        </summary>
        <div class="space-y-3 p-4 pt-0">
          <p class="text-texte-2 text-sm">{{ t('finance.profit.costDisclaimer') }}</p>
          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div
              v-for="cost in costs"
              :key="cost.key"
              data-test="profit-cost-card"
              class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
            >
              <div class="flex min-h-20 items-start justify-between gap-3">
                <div class="min-w-0 space-y-2">
                  <p class="text-texte-2 text-xs leading-snug font-medium">
                    {{ t(`finance.profit.${cost.key}`) }}
                  </p>
                  <MonoValue
                    class="text-texte text-base font-semibold"
                    :class="Number(cost.value) < 0 ? '!text-critique' : ''"
                    align="left"
                    :value="formatMoney(cost.value)"
                  />
                </div>
                <span
                  class="bg-transit-tint text-transit-texte inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                >
                  <Icon :name="cost.icon" :size="17" />
                </span>
              </div>
            </div>
          </div>
        </div>
      </details>

      <section class="border-ligne overflow-auto rounded-xl border bg-white">
        <div class="overflow-x-auto">
          <table class="w-full text-start text-sm">
            <thead>
              <tr class="border-ligne text-texte-2 border-b">
                <th class="px-3 py-2.5 font-medium">
                  {{ t('finance.profit.table.tripReference') }}
                </th>
                <th class="px-3 py-2.5 font-medium">{{ t('finance.profit.table.client') }}</th>
                <th class="px-3 py-2.5 font-medium">{{ t('finance.profit.table.product') }}</th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.profit.table.quantityLoaded') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.profit.table.quantityInvoiced') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.profit.table.transporterLossQuantity') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.profit.table.transporterLossIndemnity') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.profit.table.supplierUnitPrice') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.profit.table.realTotalCost') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.profit.table.unitSellingPrice') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.profit.table.unitProfit') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.profit.table.totalProfit') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="row.trip_reference"
                class="border-ligne border-b last:border-0"
              >
                <td class="px-3 py-2.5">
                  {{ row.trip_reference }}
                  <span
                    v-if="row.is_adjustment"
                    data-test="profit-adjustment-badge"
                    :title="t('finance.profit.adjustmentHelp')"
                    class="bg-transit-tint text-transit-texte ms-1 rounded px-1.5 py-0.5 text-xs font-medium"
                    >{{ t('finance.profit.adjustment') }}</span
                  >
                </td>
                <td class="px-3 py-2.5">{{ row.client || '—' }}</td>
                <td class="px-3 py-2.5">{{ row.product }}</td>
                <td class="px-3 py-2.5 text-end">
                  <MonoValue :value="formatQuantity(num(row.quantity_loaded))" />
                </td>
                <td class="px-3 py-2.5 text-end">
                  <MonoValue :value="formatQuantity(num(row.quantity_invoiced))" />
                </td>
                <td class="px-3 py-2.5 text-end">
                  <MonoValue :value="formatQuantity(num(row.transporter_loss_quantity))" />
                </td>
                <td class="px-3 py-2.5 text-end">
                  <MonoValue :value="formatMoney(num(row.transporter_loss_indemnity))" />
                </td>
                <td class="px-3 py-2.5 text-end">
                  <span v-if="row.is_adjustment" class="text-texte-3">—</span>
                  <MonoValue v-else :value="formatUnitMoney(num(row.supplier_unit_price))" />
                </td>
                <td class="px-3 py-2.5 text-end">
                  <MonoValue :value="formatMoney(num(row.real_total_cost))" />
                </td>
                <td class="px-3 py-2.5 text-end">
                  <span v-if="row.is_adjustment" class="text-texte-3">—</span>
                  <MonoValue v-else :value="formatUnitMoney(num(row.unit_selling_price))" />
                </td>
                <td class="px-3 py-2.5 text-end">
                  <span v-if="row.is_adjustment" class="text-texte-3">—</span>
                  <MonoValue
                    v-else
                    :value="formatUnitMoney(num(row.unit_profit))"
                    :class="
                      num(row.unit_profit) > 0
                        ? 'text-livre'
                        : num(row.unit_profit) < 0
                          ? 'text-critique'
                          : ''
                    "
                  />
                </td>
                <td class="px-3 py-2.5 text-end">
                  <MonoValue
                    :value="formatMoney(num(row.current_margin))"
                    :class="
                      num(row.current_margin) > 0
                        ? 'text-livre'
                        : num(row.current_margin) < 0
                          ? 'text-critique'
                          : ''
                    "
                  />
                </td>
              </tr>
              <tr v-if="rows.length === 0">
                <td colspan="12" class="text-texte-3 px-3 py-8 text-center">
                  {{ t('masterData.noRecords') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>
