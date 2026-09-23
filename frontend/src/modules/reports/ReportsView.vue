<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// docs/PHASE_6_PLAN.md Etape 8: report selector + interactive table +
// PDF export/print, driving GET /api/reports/{report_type}/.
//
// UI pass 2026-08-27: CSV/Excel export replaced with Imprimer/Exporter PDF.
// 2026-09-23: the result is an A4-style document (ReportSheet) built from the
// backend `document` block (docs/superpowers/specs/2026-09-23-rapports-
// document-comptable-design.md) - labels, formatting rules and totals come
// from the API, so screen, print and PDF share one structure.
import { ref, computed, watch } from 'vue'
import { usePrintScope } from '@/composables/usePrintScope'
import { useI18n } from 'vue-i18n'
import DateRangeFilter from '@/components/DateRangeFilter.vue'
import type { DateRangeValue } from '@/components/date-range'
import { useAuthStore } from '@/stores/auth'
import { createResourceApi } from '@/api/resource'
import { fetchReport, downloadReportExport } from './api'
import { REPORT_TYPES } from './types'
import type { ReportResponse } from './types'
import Button from '@/components/ui/Button.vue'
import ReportSheet from './ReportSheet.vue'
import SearchableSelect from '@/components/ui/SearchableSelect.vue'
import type { SearchableSelectOption } from '@/components/ui/SearchableSelect.vue'

const auth = useAuthStore()
const { t, te, locale } = useI18n()

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
    report.value = await fetchReport(selectedType.value, buildParams(), {
      document: true,
      lang: locale.value,
    })
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
    await downloadReportExport(selectedType.value, 'pdf', buildParams(), locale.value)
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exporting.value = false
  }
}

// Print only the sheet: usePrintScope hides everything else (spec D6).
const sheetRef = ref<InstanceType<typeof ReportSheet> | null>(null)
const sheetEl = computed<HTMLElement | null>(() => (sheetRef.value?.$el as HTMLElement) ?? null)
const sheetOrientation = computed(() => report.value?.document?.orientation ?? 'portrait')
const { print: printReport } = usePrintScope(sheetEl, sheetOrientation)

function onDateRangeChange(value: DateRangeValue) {
  dateRange.value = value
}
</script>

<template>
  <div class="space-y-6">
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

    <ReportSheet
      v-else-if="report && report.document"
      ref="sheetRef"
      :document="report.document"
      :rows="report.rows"
      :report-type="report.report_type"
    />
  </div>
</template>
