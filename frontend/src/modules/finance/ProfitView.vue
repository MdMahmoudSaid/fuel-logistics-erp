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
import Card from '@/components/ui/Card.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { formatMoney, formatQuantity, formatUnitMoney } from '@/utils/currency'

const { t } = useI18n()

interface MarginRow {
  trip_reference: string
  client: string
  product: string
  quantity: string
  supplier_unit_price: string
  transport_cost: string
  customs_cost: string
  transit_cost: string
  border_cost: string
  loading_cost: string
  additional_costs: string
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
  rows.value.reduce((sum, r) => sum + num(r.quantity) * num(r.unit_selling_price), 0),
)
const supplierCost = computed(() =>
  rows.value.reduce((sum, r) => sum + num(r.quantity) * num(r.supplier_unit_price), 0),
)
const transportCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.transport_cost), 0))
const customsCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.customs_cost), 0))
const transitCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.transit_cost), 0))
const borderCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.border_cost), 0))
const loadingCost = computed(() => rows.value.reduce((sum, r) => sum + num(r.loading_cost), 0))
const otherCosts = computed(() => rows.value.reduce((sum, r) => sum + num(r.additional_costs), 0))

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
      <p class="text-texte-2 border-ligne rounded-xl border border-dashed bg-white px-4 py-2.5 text-sm">
        {{ t('finance.profit.costDisclaimer') }}
      </p>

      <section class="grid grid-cols-3 gap-4 lg:grid-cols-5">
        <Card>
          <p class="text-texte-2 text-xs">{{ t('finance.profit.periodProfit') }}</p>
          <MonoValue
            class="text-lg font-semibold"
            align="left"
            :value="formatMoney(periodProfit)"
          />
        </Card>
        <Card>
          <p class="text-texte-2 text-xs">{{ t('finance.profit.tripsCount') }}</p>
          <MonoValue class="text-lg font-semibold" align="left" :value="String(rows.length)" />
        </Card>
        <Card>
          <p class="text-texte-2 text-xs">{{ t('finance.profit.revenue') }}</p>
          <MonoValue class="text-lg font-semibold" align="left" :value="formatMoney(revenue)" />
        </Card>
        <Card>
          <p class="text-texte-2 text-xs">{{ t('finance.profit.supplierCost') }}</p>
          <MonoValue
            class="text-lg font-semibold"
            align="left"
            :value="formatMoney(supplierCost)"
          />
        </Card>
        <Card>
          <p class="text-texte-2 text-xs">{{ t('finance.profit.transportCost') }}</p>
          <MonoValue
            class="text-lg font-semibold"
            align="left"
            :value="formatMoney(transportCost)"
          />
        </Card>
        <Card>
          <p class="text-texte-2 text-xs">{{ t('finance.profit.customsCost') }}</p>
          <MonoValue
            class="text-lg font-semibold"
            align="left"
            :value="formatMoney(customsCost)"
          />
        </Card>
        <Card>
          <p class="text-texte-2 text-xs">{{ t('finance.profit.transitCost') }}</p>
          <MonoValue
            class="text-lg font-semibold"
            align="left"
            :value="formatMoney(transitCost)"
          />
        </Card>
        <Card>
          <p class="text-texte-2 text-xs">{{ t('finance.profit.borderCost') }}</p>
          <MonoValue
            class="text-lg font-semibold"
            align="left"
            :value="formatMoney(borderCost)"
          />
        </Card>
        <Card>
          <p class="text-texte-2 text-xs">{{ t('finance.profit.loadingCost') }}</p>
          <MonoValue
            class="text-lg font-semibold"
            align="left"
            :value="formatMoney(loadingCost)"
          />
        </Card>
        <Card>
          <p class="text-texte-2 text-xs">{{ t('finance.profit.otherCosts') }}</p>
          <MonoValue
            class="text-lg font-semibold"
            align="left"
            :value="formatMoney(otherCosts)"
          />
        </Card>
      </section>

      <section class="border-ligne overflow-auto rounded-xl border bg-white">
        <table class="w-full text-start text-sm">
          <thead>
            <tr class="border-ligne text-texte-2 border-b">
              <th class="px-3 py-2.5 font-medium">{{ t('finance.profit.table.tripReference') }}</th>
              <th class="px-3 py-2.5 font-medium">{{ t('finance.profit.table.client') }}</th>
              <th class="px-3 py-2.5 font-medium">{{ t('finance.profit.table.product') }}</th>
              <th class="px-3 py-2.5 text-end font-medium">
                {{ t('finance.profit.table.quantity') }}
              </th>
              <th class="px-3 py-2.5 text-end font-medium">
                {{ t('finance.profit.table.supplierUnitPrice') }}
              </th>
              <th class="px-3 py-2.5 text-end font-medium">
                {{ t('finance.profit.table.unitCost') }}
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
                <MonoValue :value="formatQuantity(num(row.quantity))" />
              </td>
              <td class="px-3 py-2.5 text-end">
                <MonoValue :value="formatUnitMoney(num(row.supplier_unit_price))" />
              </td>
              <td class="px-3 py-2.5 text-end">
                <MonoValue :value="formatUnitMoney(num(row.unit_cost))" />
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
              <td colspan="9" class="text-texte-3 px-3 py-8 text-center">
                {{ t('masterData.noRecords') }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
