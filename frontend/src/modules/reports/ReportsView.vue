<script setup lang="ts">
// docs/PHASE_6_PLAN.md Etape 8: report selector + interactive table +
// CSV/Excel export, driving GET /api/reports/{report_type}/.
import { ref, computed } from 'vue'
import DateRangeFilter from '@/components/DateRangeFilter.vue'
import type { DateRangeValue } from '@/components/date-range'
import { useAuthStore } from '@/stores/auth'
import { fetchReport, downloadReportExport } from './api'
import { REPORT_TYPES } from './types'
import type { ReportResponse } from './types'

const auth = useAuthStore()
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
    error.value = 'Could not load this report.'
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
    error.value = 'Could not export this report.'
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
    <h2 class="text-lg font-semibold text-slate-800">Reports</h2>

    <div class="flex flex-wrap items-end gap-3 rounded border bg-white p-4">
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-slate-500">Report type</span>
        <select v-model="selectedType" class="rounded border px-2 py-1.5">
          <option v-for="option in REPORT_TYPES" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </label>

      <label v-if="currentOption?.idParam" class="flex flex-col gap-1 text-sm">
        <span class="text-slate-500">{{ currentOption.idLabel }}</span>
        <input v-model="entityId" type="text" class="rounded border px-2 py-1.5" />
      </label>

      <DateRangeFilter @change="onDateRangeChange" />

      <button
        class="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        :disabled="loading"
        @click="runReport"
      >
        Run report
      </button>

      <template v-if="canExport && report">
        <button
          class="rounded border px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-50"
          :disabled="exporting"
          @click="exportReport('csv')"
        >
          Export CSV
        </button>
        <button
          class="rounded border px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-50"
          :disabled="exporting"
          @click="exportReport('xlsx')"
        >
          Export Excel
        </button>
      </template>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">Loading…</p>

    <section v-else-if="report" class="overflow-auto rounded border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-b text-slate-500">
            <th v-for="field in report.fields" :key="field" class="px-2 py-1.5 font-medium">
              {{ field }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in report.rows" :key="index" class="border-b last:border-0">
            <td v-for="field in report.fields" :key="field" class="px-2 py-1.5">
              {{ cellValue(row, field) }}
            </td>
          </tr>
          <tr v-if="report.rows.length === 0">
            <td :colspan="report.fields.length" class="px-2 py-4 text-center text-slate-400">
              No data for this selection.
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
