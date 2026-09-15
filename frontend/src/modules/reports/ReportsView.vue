<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// docs/PHASE_6_PLAN.md Etape 8: report selector + interactive table +
// PDF export/print, driving GET /api/reports/{report_type}/.
//
// UI pass 2026-08-27: CSV/Excel export replaced with Imprimer/Exporter PDF
// (docs/Final_edit.md-adjacent request), and cells now format currency,
// translate raw enum values and show status as pastel badges instead of
// printing the raw DB string.
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import DateRangeFilter from '@/components/DateRangeFilter.vue'
import type { DateRangeValue } from '@/components/date-range'
import { useAuthStore } from '@/stores/auth'
import { createResourceApi } from '@/api/resource'
import { fetchReport, downloadReportExport } from './api'
import { REPORT_TYPES } from './types'
import type { ReportResponse } from './types'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import SearchableSelect from '@/components/ui/SearchableSelect.vue'
import type { SearchableSelectOption } from '@/components/ui/SearchableSelect.vue'
import { formatMoney, formatUnitMoney, formatQuantity } from '@/utils/currency'

const auth = useAuthStore()
const { t, te } = useI18n()

// Endpoints backing the searchable ID selectors, one per REPORT_TYPES
// idParam. `labelKey` is the field to display - most master-data
// entities use `name`, trucks identify themselves by `internal_id`.
const ENTITY_ENDPOINTS: Record<string, { path: string; labelKey: string }> = {
  customer_id: { path: '/customers/', labelKey: 'name' },
  supplier_id: { path: '/suppliers/', labelKey: 'name' },
  transporter_id: { path: '/transporters/', labelKey: 'name' },
  truck_id: { path: '/trucks/', labelKey: 'internal_id' },
  bank_account_id: { path: '/bank-accounts/', labelKey: 'name' },
  cash_account_id: { path: '/cash-accounts/', labelKey: 'name' },
  shareholder_id: { path: '/shareholders/', labelKey: 'name' },
}

const entityOptionsCache = ref<Record<string, SearchableSelectOption[]>>({})

async function loadEntityOptions(idParam: string) {
  if (entityOptionsCache.value[idParam]) return
  const config = ENTITY_ENDPOINTS[idParam]
  if (!config) return
  try {
    const resource = createResourceApi<Record<string, unknown>>(config.path)
    const data = await resource.list()
    entityOptionsCache.value[idParam] = data.results.map((row) => ({
      value: String(row.id),
      label: String(row[config.labelKey] ?? row.id),
    }))
  } catch {
    // Background prefetch for the searchable selector - a failure just
    // leaves it empty, it isn't worth surfacing as a page-level error.
  }
}

function reportLabel(value: string): string {
  const key = `reports.types.${value}.label`
  return te(key) ? t(key) : value
}
function reportIdLabel(value: string): string {
  const key = `reports.types.${value}.idLabel`
  return te(key) ? t(key) : value
}
function fieldLabel(field: string): string {
  const key = `reports.fields.${field}`
  return te(key) ? t(key) : field.replace(/_/g, ' ')
}
const canExport = computed(() => auth.can('reports', 'export'))

const selectedType = ref(REPORT_TYPES[0]!.value)
const entityId = ref('')
const dateRange = ref<DateRangeValue>({})
const report = ref<ReportResponse | null>(null)
const loading = ref(false)
const error = ref('')
const exporting = ref(false)

const currentOption = computed(() =>
  REPORT_TYPES.find((option) => option.value === selectedType.value),
)

const entityOptions = computed(() => {
  const idParam = currentOption.value?.idParam
  return idParam ? (entityOptionsCache.value[idParam] ?? []) : []
})

watch(
  () => currentOption.value?.idParam,
  (idParam) => {
    entityId.value = ''
    if (idParam) loadEntityOptions(idParam)
  },
  { immediate: true },
)

function buildParams(): Record<string, string | undefined> {
  const params: Record<string, string | undefined> = { ...dateRange.value }
  if (currentOption.value?.idParam && entityId.value) {
    params[currentOption.value.idParam] = entityId.value
  }
  return params
}

async function runReport() {
  loading.value = true
  error.value = ''
  try {
    report.value = await fetchReport(selectedType.value, buildParams())
  } catch {
    error.value = t('reports.loadError')
    report.value = null
  } finally {
    loading.value = false
  }
}

async function exportPdf() {
  exporting.value = true
  try {
    await downloadReportExport(selectedType.value, 'pdf', buildParams())
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exporting.value = false
  }
}

function printReport() {
  window.print()
}

function onDateRangeChange(value: DateRangeValue) {
  dateRange.value = value
}

// --- Cell formatting/translation ---------------------------------------
//
// Report FIELDS are shared across 17 report types with overlapping field
// names but different meaning (e.g. "status" is SupplierOrder.Status on
// purchase-report but Trip.Status on trip-report/truck-history) - every
// lookup below is keyed by `${reportType}.${field}` for that reason, not
// just by field name.

const MONEY_FIELDS = new Set([
  'debit',
  'credit',
  'balance',
  'amount',
  'outstanding',
  'total_amount',
  'subtotal',
  'transport_cost',
  'customs_cost',
  'transit_cost',
  'border_cost',
  'loading_cost',
  'additional_costs',
  'base_amount',
  'deduction_amount',
  'advance_applied',
  'net_amount',
  'current_margin',
])

const UNIT_MONEY_FIELDS = new Set([
  'unit_price',
  'unit_selling_price',
  'supplier_unit_price',
  'unit_cost',
  'unit_profit',
])

const QUANTITY_FIELDS = new Set([
  'quantity',
  'quantity_litres',
  'quantity_loaded',
  'delivered_quantity',
  'loaded_quantity',
  'received_quantity',
  'loss_quantity',
  'tolerance_quantity',
  'chargeable_loss_quantity',
])

// field -> i18n namespace for translating the raw DB value.
const ENUM_NAMESPACE: Record<string, string> = {
  'customer-statement.type': 'statementType',
  'supplier-statement.type': 'statementType',
  'shareholder-statement.type': 'statementType',
  'bank-statement.type': 'transactionType',
  'cash-statement.type': 'transactionType',
  'purchase-report.status': 'purchaseOrderStatus',
  'expense-report.status': 'expenseStatus',
  'expense-report.category': 'expenseCategory',
  'expense-report.calculation_method': 'expenseCalcMethod',
  'trip-report.status': 'trips.status',
  'truck-history.status': 'trips.status',
}

// Which enum fields render as a pastel Badge instead of plain translated
// text - state-like columns only (spec: "Validé, En attente, Payé, Non
// payé"), not transaction-kind columns like statement "type".
const BADGE_FIELDS = new Set([
  'purchase-report.status',
  'expense-report.status',
  'trip-report.status',
  'truck-history.status',
])

type BadgeVariant = 'livre' | 'transit' | 'ecart' | 'critique' | 'neutre'

function badgeVariant(namespace: string, value: string): BadgeVariant {
  if (namespace === 'purchaseOrderStatus') {
    if (value === 'CONFIRMED') return 'livre'
    if (value === 'CANCELLED') return 'critique'
    return 'neutre'
  }
  if (namespace === 'expenseStatus') {
    if (value === 'PAID') return 'livre'
    if (value === 'PARTIALLY_PAID') return 'ecart'
    if (value === 'CANCELLED') return 'neutre'
    return 'critique' // UNPAID
  }
  if (namespace === 'trips.status') {
    if (value === 'DELIVERED' || value === 'COMPLETED') return 'livre'
    if (value === 'CANCELLED' || value === 'BLOCKED') return 'critique'
    if (value === 'QUANTITY_CONTROL') return 'ecart'
    return 'transit'
  }
  return 'neutre'
}

// Sign/role-based coloring for money cells (spec: "Entrées / Solde
// positif: vert; Sorties / Dettes / Solde négatif: rouge"). 'auto' colors
// by the value's own sign; fixed 'emerald'/'rose' cover fields whose
// meaning as an inflow/outflow doesn't depend on sign (e.g. a supplier
// statement's positive "balance" is always money the company owes, never
// good news, even though it's stored as a positive number).
const MONEY_TONE: Record<string, 'emerald' | 'rose' | 'auto'> = {
  'customer-statement.debit': 'rose',
  'customer-statement.credit': 'emerald',
  'customer-statement.balance': 'auto',
  'supplier-statement.debit': 'rose',
  'supplier-statement.credit': 'emerald',
  'supplier-statement.balance': 'rose',
  'shareholder-statement.debit': 'rose',
  'shareholder-statement.credit': 'emerald',
  'shareholder-statement.balance': 'auto',
  'customer-outstanding.outstanding': 'emerald',
  'supplier-outstanding.outstanding': 'rose',
  'transporter-outstanding.outstanding': 'rose',
  'transporter-statement.net_amount': 'rose',
}

type FieldKind = 'badge' | 'enum' | 'money' | 'unitMoney' | 'quantity' | 'plain'

// Keyed off the *loaded* report's type, not the dropdown's current
// selection - the two can briefly differ (switching the dropdown after a
// report is already displayed, before clicking "Lancer le rapport" again),
// and it's the rendered rows whose fields must be classified correctly.
const activeReportType = computed(() => report.value?.report_type ?? selectedType.value)

function fieldKind(field: string): FieldKind {
  const key = `${activeReportType.value}.${field}`
  if (BADGE_FIELDS.has(key)) return 'badge'
  if (ENUM_NAMESPACE[key]) return 'enum'
  if (MONEY_FIELDS.has(field)) return 'money'
  if (UNIT_MONEY_FIELDS.has(field)) return 'unitMoney'
  if (QUANTITY_FIELDS.has(field)) return 'quantity'
  return 'plain'
}

function enumNamespace(field: string): string {
  return ENUM_NAMESPACE[`${activeReportType.value}.${field}`] ?? ''
}

function enumLabel(field: string, row: Record<string, unknown>): string {
  const raw = row[field]
  if (raw === null || raw === undefined || raw === '') return '—'
  const namespace = enumNamespace(field)
  const key = `${namespace}.${String(raw)}`
  return te(key) ? t(key) : String(raw)
}

function moneyToneClass(field: string, row: Record<string, unknown>): string {
  const raw = row[field]
  if (raw === null || raw === undefined || raw === '') return ''
  // bank-statement/cash-statement "amount" is always stored positive - its
  // in/out meaning lives on the row's own "type" column instead of sign.
  if (field === 'amount' && typeof row.type === 'string') {
    if (row.type === 'MONEY_IN') return 'text-emerald-600'
    if (row.type === 'MONEY_OUT') return 'text-rose-600'
  }
  const rule = MONEY_TONE[`${activeReportType.value}.${field}`]
  const numeric = Number(raw)
  if (rule === 'emerald') return 'text-emerald-600'
  if (rule === 'rose') return 'text-rose-600'
  if (rule === 'auto') return numeric >= 0 ? 'text-emerald-600' : 'text-rose-600'
  return numeric < 0 ? 'text-rose-600' : ''
}

function moneyCellValue(field: string, row: Record<string, unknown>): string {
  const raw = row[field]
  if (raw === null || raw === undefined || raw === '') return '—'
  return formatMoney(raw as string | number)
}

function unitMoneyCellValue(field: string, row: Record<string, unknown>): string {
  const raw = row[field]
  if (raw === null || raw === undefined || raw === '') return '—'
  return formatUnitMoney(raw as string | number)
}

function quantityCellValue(field: string, row: Record<string, unknown>): string {
  const raw = row[field]
  if (raw === null || raw === undefined || raw === '') return '—'
  return formatQuantity(raw as string | number)
}

function plainCellValue(row: Record<string, unknown>, field: string): string {
  const value = row[field]
  return value === null || value === undefined ? '—' : String(value)
}
</script>

<template>
  <div class="max-w-6xl space-y-6">
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">
      {{ t('reports.title') }}
    </h1>

    <div
      class="no-print border-ligne flex flex-wrap items-end gap-3 rounded-xl border bg-surface p-4"
    >
      <label class="space-y-1.5 text-sm">
        <span class="text-texte-2 block font-medium">{{ t('reports.reportType') }}</span>
        <select
          v-model="selectedType"
          class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        >
          <option v-for="option in REPORT_TYPES" :key="option.value" :value="option.value">
            {{ reportLabel(option.value) }}
          </option>
        </select>
      </label>

      <label v-if="currentOption?.idParam" class="w-64 space-y-1.5 text-sm">
        <span class="text-texte-2 block font-medium">{{ reportIdLabel(currentOption.value) }}</span>
        <SearchableSelect v-model="entityId" :options="entityOptions" />
      </label>

      <DateRangeFilter @change="onDateRangeChange" />

      <Button variant="primary" :disabled="loading" @click="runReport">{{
        t('reports.runReport')
      }}</Button>

      <template v-if="report">
        <Button variant="ghost" @click="printReport">
          {{ t('reports.print') }}
        </Button>
        <Button v-if="canExport" variant="ghost" :disabled="exporting" @click="exportPdf">
          {{ t('reports.exportPdf') }}
        </Button>
      </template>
    </div>

    <AppAlert v-if="error" :message="error" />
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <section v-else-if="report" class="border-ligne overflow-auto rounded-xl border bg-white">
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-ligne text-texte-2 border-b">
              <th v-for="field in report.fields" :key="field" class="px-3 py-2.5 font-medium">
                {{ fieldLabel(field) }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, index) in report.rows"
              :key="index"
              class="border-ligne border-b last:border-0"
            >
              <td v-for="field in report.fields" :key="field" class="px-3 py-2.5">
                <Badge
                  v-if="fieldKind(field) === 'badge'"
                  :variant="badgeVariant(enumNamespace(field), String(row[field]))"
                >
                  {{ enumLabel(field, row) }}
                </Badge>
                <span v-else-if="fieldKind(field) === 'enum'">{{ enumLabel(field, row) }}</span>
                <span v-else-if="fieldKind(field) === 'money'" :class="moneyToneClass(field, row)">
                  {{ moneyCellValue(field, row) }}
                </span>
                <span v-else-if="fieldKind(field) === 'unitMoney'">{{
                  unitMoneyCellValue(field, row)
                }}</span>
                <span v-else-if="fieldKind(field) === 'quantity'">{{
                  quantityCellValue(field, row)
                }}</span>
                <span v-else>{{ plainCellValue(row, field) }}</span>
              </td>
            </tr>
            <tr v-if="report.rows.length === 0">
              <td :colspan="report.fields.length" class="text-texte-3 px-3 py-8 text-center">
                {{ t('reports.noData') }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
