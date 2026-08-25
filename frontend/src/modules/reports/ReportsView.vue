<script setup lang="ts">
// docs/PHASE_6_PLAN.md Etape 8: report selector + interactive table +
// CSV/Excel export, driving GET /api/reports/{report_type}/.
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
import SearchableSelect from '@/components/ui/SearchableSelect.vue'
import type { SearchableSelectOption } from '@/components/ui/SearchableSelect.vue'

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

async function exportReport(format: 'csv' | 'xlsx') {
  exporting.value = true
  try {
    await downloadReportExport(selectedType.value, format, buildParams())
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exporting.value = false
  }
}

function onDateRangeChange(value: DateRangeValue) {
  dateRange.value = value
}

function cellValue(row: Record<string, unknown>, field: string): string {
  const value = row[field]
  return value === null || value === undefined ? '—' : String(value)
}
</script>

<template>
  <div class="max-w-6xl space-y-6">
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">
      {{ t('reports.title') }}
    </h1>

    <div class="border-ligne flex flex-wrap items-end gap-3 rounded-xl border bg-surface p-4">
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

      <template v-if="canExport && report">
        <Button variant="ghost" :disabled="exporting" @click="exportReport('csv')">
          {{ t('reports.exportCsv') }}
        </Button>
        <Button variant="ghost" :disabled="exporting" @click="exportReport('xlsx')">
          {{ t('reports.exportExcel') }}
        </Button>
      </template>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <section v-else-if="report" class="border-ligne overflow-auto rounded-xl border bg-white">
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
              {{ cellValue(row, field) }}
            </td>
          </tr>
          <tr v-if="report.rows.length === 0">
            <td :colspan="report.fields.length" class="text-texte-3 px-3 py-8 text-center">
              {{ t('reports.noData') }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
