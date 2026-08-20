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
import Button from '@/components/ui/Button.vue'

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
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">Reports</h1>

    <div class="border-ligne flex flex-wrap items-end gap-3 rounded-xl border bg-surface p-4">
      <label class="space-y-1.5 text-sm">
        <span class="text-texte-2 block font-medium">Report type</span>
        <select
          v-model="selectedType"
          class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        >
          <option v-for="option in REPORT_TYPES" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </label>

      <label v-if="currentOption?.idParam" class="space-y-1.5 text-sm">
        <span class="text-texte-2 block font-medium">{{ currentOption.idLabel }}</span>
        <input
          v-model="entityId"
          type="text"
          class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        />
      </label>

      <DateRangeFilter @change="onDateRangeChange" />

      <Button variant="primary" :disabled="loading" @click="runReport">Run report</Button>

      <template v-if="canExport && report">
        <Button variant="ghost" :disabled="exporting" @click="exportReport('csv')">
          Export CSV
        </Button>
        <Button variant="ghost" :disabled="exporting" @click="exportReport('xlsx')">
          Export Excel
        </Button>
      </template>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">Loading…</p>

    <section v-else-if="report" class="border-ligne overflow-auto rounded-xl border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th v-for="field in report.fields" :key="field" class="px-3 py-2.5 font-medium">
              {{ field }}
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
              No data for this selection.
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
