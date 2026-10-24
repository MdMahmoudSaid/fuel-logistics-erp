<script setup lang="ts">
// A4-style report document (docs/superpowers/specs/2026-09-23-rapports-
// document-comptable-design.md, section Frontend). Renders exactly what the
// backend `document` says - masthead, general information, table(s), opening
// balance row, summary - so the screen, print and the backend PDF share one
// structure. On phones the sheet keeps its A4 width and scrolls horizontally
// inside .report-sheet-scroll; the PDF is never cut.
import { computed } from 'vue'
import Badge from '@/components/ui/Badge.vue'
import { BRAND_ICON } from '@/brand'
import type { ReportDocument, ReportTable } from './types'
import {
  badgeVariant,
  cellText,
  isEmphasisRow,
  moneyToneClass,
  summaryText,
  tableRows,
} from './reportCells'

defineOptions({ name: 'ReportSheet' })

const props = defineProps<{
  document: ReportDocument
  rows: Record<string, unknown>[]
  reportType: string
}>()

const sheetWidth = computed(() => (props.document.orientation === 'landscape' ? '297mm' : '210mm'))

function openingIndex(table: ReportTable): number {
  const opening = props.document.opening_balance
  return opening ? table.columns.findIndex((column) => column.field === opening.column) : -1
}
</script>

<template>
  <div class="report-sheet-scroll overflow-x-auto py-4">
    <article
      class="report-sheet mx-auto bg-white text-sm shadow-sm ring-1 ring-black/10"
      :dir="document.direction"
      :data-orientation="document.orientation"
      :style="{ width: sheetWidth, minWidth: sheetWidth, padding: '12mm' }"
    >
      <!-- A <div>, not a <header>: style.css hides every <header> (the app topbar) in print. -->
      <div class="report-masthead flex items-center gap-4 border-b-[3px] border-[#0b5cab] pb-3">
        <img :src="BRAND_ICON" alt="" class="size-14 shrink-0" />
        <div>
          <p class="text-2xl leading-tight font-semibold">{{ document.company.name }}</p>
          <p v-if="document.company.tagline" class="text-texte-3 text-xs">
            {{ document.company.tagline }}
          </p>
        </div>
      </div>

      <h2 class="mt-5 text-3xl font-semibold">{{ document.title }}</h2>

      <dl class="report-info mt-3 grid grid-cols-2 gap-x-8 gap-y-1">
        <div v-for="item in document.info" :key="item.key" class="flex gap-3">
          <dt class="text-texte-3 w-28 shrink-0">{{ item.label }}</dt>
          <dd>{{ item.value }}</dd>
        </div>
      </dl>
      <hr class="mt-4 mb-5 border-t border-black/20" />

      <section v-for="(table, tableIndex) in document.tables" :key="table.key" class="mb-5">
        <h3 v-if="table.title" class="mb-1.5 text-base font-semibold">{{ table.title }}</h3>
        <table class="report-table w-full border-collapse text-start">
          <thead>
            <tr>
              <th
                v-for="column in table.columns"
                :key="column.field"
                class="border border-black/25 bg-[#e6edf5] px-2 py-1.5 font-semibold"
                :class="column.align === 'end' ? 'text-end' : 'text-start'"
              >
                {{ column.label }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-if="tableIndex === 0 && document.opening_balance"
              class="report-opening-row bg-sable/60 font-semibold"
            >
              <template v-if="openingIndex(table) > 0">
                <td :colspan="openingIndex(table)" class="border border-black/25 px-2 py-1.5">
                  {{ document.opening_balance.label }}
                </td>
                <td class="border border-black/25 px-2 py-1.5 text-end">
                  {{
                    cellText(
                      { ...table.columns[openingIndex(table)]!, kind: 'money' },
                      document.opening_balance.value,
                    )
                  }}
                </td>
                <td
                  v-for="column in table.columns.slice(openingIndex(table) + 1)"
                  :key="column.field"
                  class="border border-black/25"
                />
              </template>
              <template v-else>
                <td class="border border-black/25 px-2 py-1.5 text-end">
                  {{
                    cellText(
                      { ...table.columns[0]!, kind: 'money' },
                      document.opening_balance.value,
                    )
                  }}
                </td>
                <td :colspan="table.columns.length - 1" class="border border-black/25 px-2 py-1.5">
                  {{ document.opening_balance.label }}
                </td>
              </template>
            </tr>
            <tr
              v-for="(row, index) in tableRows(table, rows)"
              :key="index"
              class="report-row"
              :class="isEmphasisRow(table, row) ? 'bg-sable/60 font-semibold' : ''"
            >
              <td
                v-for="column in table.columns"
                :key="column.field"
                class="border border-black/25 px-2 py-1.5 align-middle"
                :class="column.align === 'end' ? 'text-end' : 'text-start'"
              >
                <Badge
                  v-if="column.kind === 'status'"
                  :variant="badgeVariant(column.namespace, String(row[column.field]))"
                >
                  {{ cellText(column, row[column.field]) }}
                </Badge>
                <span
                  v-else-if="column.kind === 'money'"
                  :class="moneyToneClass(reportType, column, row)"
                >
                  {{ cellText(column, row[column.field]) }}
                </span>
                <span v-else :class="column.kind === 'ref' ? 'whitespace-nowrap' : ''">{{
                  cellText(column, row[column.field])
                }}</span>
              </td>
            </tr>
            <tr v-if="tableRows(table, rows).length === 0">
              <td
                :colspan="table.columns.length"
                class="report-empty text-texte-3 border border-black/25 px-2 py-8 text-center"
              >
                {{ document.empty_text }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <table class="report-summary ms-auto mt-6 w-[120mm] border-collapse">
        <tbody>
          <tr
            v-for="line in document.summary"
            :key="line.key"
            class="border-b border-black/15"
            :class="line.emphasis ? 'bg-sable/60 border-t-2 border-t-black font-semibold' : ''"
          >
            <td class="px-2 py-1.5">{{ line.label }}</td>
            <td class="px-2 py-1.5 text-end">{{ summaryText(line) }}</td>
          </tr>
        </tbody>
      </table>

      <footer
        v-if="document.company.lines?.length || document.company.banks?.length"
        class="report-company-footer text-texte-3 mt-8 border-t border-black/20 pt-2 text-[11px] leading-relaxed"
      >
        <p class="text-texte font-semibold">{{ document.company.name }}</p>
        <p v-if="document.company.lines?.length">{{ document.company.lines.join('   |   ') }}</p>
        <p v-if="document.company.banks?.length" class="text-[#0b5cab]">
          {{
            document.company.banks
              .map((b) => `${b.bank} : ${b.account}${b.swift ? ` (SWIFT ${b.swift})` : ''}`)
              .join('   |   ')
          }}
        </p>
      </footer>
    </article>
  </div>
</template>
