<script setup lang="ts">
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
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import DateRangeFilter from '@/components/DateRangeFilter.vue'
import type { DateRangeValue } from '@/components/date-range'
import { fetchReport } from '@/modules/reports/api'
import { fetchShareholderProfitPreview } from './api'
import type { ShareholderProfitPreview } from './types'
import Badge from '@/components/ui/Badge.vue'
import Icon from '@/components/ui/Icon.vue'
import type { IconName } from '@/components/ui/Icon.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { formatMoney, formatQuantity, formatUnitMoney } from '@/utils/currency'

const { t } = useI18n()

interface MarginRow {
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
const loading = ref(false)
const error = ref('')
const preview = ref<ShareholderProfitPreview | null>(null)

function num(value: string): number {
  return Number(value)
}

const periodProfit = computed(() => rows.value.reduce((sum, r) => sum + num(r.current_margin), 0))
const revenue = computed(() =>
  rows.value.reduce((sum, r) => sum + num(r.quantity_invoiced) * num(r.unit_selling_price), 0),
)
const supplierCost = computed(() =>
  rows.value.reduce((sum, r) => sum + num(r.quantity_loaded) * num(r.supplier_unit_price), 0),
)
const lossIndemnity = computed(() =>
  rows.value.reduce((sum, r) => sum + num(r.transporter_loss_indemnity), 0),
)
const transportCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.transport_cost), 0))
const customsCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.customs_cost), 0))
const transitCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.transit_cost), 0))
const borderCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.border_cost), 0))
const loadingCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.loading_cost), 0))
const otherCosts = computed(() => rows.value.reduce((sum, r) => sum + num(r.additional_costs), 0))
const costs = computed(() => [
  { key: 'supplierCost', value: supplierCost.value, icon: 'fuel' as IconName },
  { key: 'transportCost', value: transportCost.value, icon: 'truck' as IconName },
  { key: 'lossIndemnity', value: lossIndemnity.value, icon: 'circle-dollar-sign' as IconName },
  { key: 'customsCost', value: customsCost.value, icon: 'landmark' as IconName },
  { key: 'transitCost', value: transitCost.value, icon: 'route' as IconName },
  { key: 'borderCost', value: borderCost.value, icon: 'shield-check' as IconName },
  { key: 'loadingCost', value: loadingCost.value, icon: 'package' as IconName },
  { key: 'otherCosts', value: otherCosts.value, icon: 'file-text' as IconName },
])

const periodProfitTone = computed(() =>
  periodProfit.value < 0 ? 'text-critique' : periodProfit.value > 0 ? 'text-livre' : 'text-texte',
)

async function loadRows() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string | undefined> = { ...dateRange.value }
    const report = await fetchReport('margin-report', params)
    rows.value = report.rows as unknown as MarginRow[]
  } catch {
    error.value = t('finance.profit.loadError')
    rows.value = []
  } finally {
    loading.value = false
  }
}

async function loadPreview() {
  try {
    preview.value = await fetchShareholderProfitPreview()
  } catch {
    preview.value = null
  }
}

function onDateRangeChange(value: DateRangeValue) {
  dateRange.value = value
  loadRows()
}

onMounted(() => {
  loadPreview()
})
</script>

<template>
  <div class="max-w-6xl space-y-6">
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">
      {{ t('finance.profit.title') }}
    </h1>

    <!-- Live, indicative current profit - same read-only preview shown on
         the Actionnaires/Associes page, never a stored figure. -->
    <div v-if="preview" class="border-ecart bg-ecart-tint rounded-xl border p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <Badge variant="transit">{{ t('finance.shareholder.preview.badge') }}</Badge>
          <p class="text-texte-2 text-sm">{{ t('finance.profit.currentProfit') }}</p>
        </div>
        <MonoValue
          class="text-lg font-semibold"
          :value="formatMoney(preview.current_profit)"
        />
      </div>
    </div>

    <div class="border-ligne flex flex-wrap items-end gap-3 rounded-xl border bg-white p-4">
      <DateRangeFilter @change="onDateRangeChange" />
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else>
      <section class="grid gap-3 lg:grid-cols-3">
        <div
          data-test="profit-summary-card"
          class="border-ligne rounded-lg border bg-white p-4 shadow-sm lg:col-span-2"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="space-y-1">
              <div class="text-texte flex items-center gap-2">
                <span
                  class="bg-livre-tint text-livre-texte inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                >
                  <Icon name="trending-up" :size="18" />
                </span>
                <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
                  {{ t('finance.profit.accountingProfit') }}
                </p>
              </div>
              <p class="text-texte-2 max-w-2xl text-sm">
                {{ t('finance.profit.accountingProfitHelp') }}
              </p>
            </div>
            <MonoValue
              class="text-2xl font-semibold"
              :class="periodProfitTone"
              :value="formatMoney(periodProfit)"
            />
          </div>
          <div class="border-ligne mt-4 grid gap-3 border-t pt-4 sm:grid-cols-2">
            <div>
              <p class="text-texte-2 text-xs font-semibold uppercase">
                {{ t('finance.profit.revenue') }}
              </p>
              <MonoValue class="font-semibold" align="left" :value="formatMoney(revenue)" />
            </div>
            <div>
              <p class="text-texte-2 text-xs font-semibold uppercase">
                {{ t('finance.profit.tripsCount') }}
              </p>
              <MonoValue class="font-semibold" align="left" :value="String(rows.length)" />
            </div>
          </div>
        </div>

        <div class="grid gap-3">
          <div
            data-test="profit-summary-card"
            class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
          >
            <div class="text-texte flex items-center gap-2">
              <span
                class="bg-transit-tint text-transit-texte inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
              >
                <Icon name="receipt-text" :size="17" />
              </span>
              <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
                {{ t('finance.profit.receivedProfit') }}
              </p>
            </div>
            <p class="text-texte-2 mt-1 text-sm">{{ t('finance.profit.receivedProfitHelp') }}</p>
          </div>
          <div
            data-test="profit-summary-card"
            class="border-ligne rounded-lg border bg-white p-4 shadow-sm"
          >
            <div class="text-texte flex items-center gap-2">
              <span
                class="bg-transit-tint text-transit-texte inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
              >
                <Icon name="chart-no-axes-combined" :size="17" />
              </span>
              <p class="text-texte-2 text-xs font-medium tracking-wide uppercase">
                {{ t('finance.profit.distributableProfit') }}
              </p>
            </div>
            <p class="text-texte-2 mt-1 text-sm">
              {{ t('finance.profit.distributableProfitHelp') }}
            </p>
          </div>
        </div>
      </section>

      <p class="border-ligne bg-sable text-texte rounded-lg border px-4 py-3 text-sm">
        {{ t('finance.profit.distributionNote') }}
      </p>

      <section class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
      </section>

      <section class="border-ligne overflow-auto rounded-xl border bg-white">
        <table class="w-full text-start text-sm">
          <thead>
            <tr class="border-ligne text-texte-2 border-b">
              <th class="px-3 py-2.5 font-medium">{{ t('finance.profit.table.tripReference') }}</th>
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
              <td class="px-3 py-2.5">{{ row.trip_reference }}</td>
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
                <MonoValue :value="formatUnitMoney(num(row.supplier_unit_price))" />
              </td>
              <td class="px-3 py-2.5 text-end">
                <MonoValue :value="formatMoney(num(row.real_total_cost))" />
              </td>
              <td class="px-3 py-2.5 text-end">
                <MonoValue :value="formatUnitMoney(num(row.unit_selling_price))" />
              </td>
              <td class="px-3 py-2.5 text-end">
                <MonoValue
                  :value="formatUnitMoney(num(row.unit_profit))"
                  :class="num(row.unit_profit) < 0 ? 'text-critique' : ''"
                />
              </td>
              <td class="px-3 py-2.5 text-end">
                <MonoValue
                  :value="formatMoney(num(row.current_margin))"
                  :class="num(row.current_margin) < 0 ? 'text-critique' : ''"
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
      </section>
    </template>
  </div>
</template>
