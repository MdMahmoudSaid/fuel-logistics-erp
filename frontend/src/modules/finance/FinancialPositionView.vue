<script setup lang="ts">
// "Situation financiere" (client request 2026-10-17): what the company owns on
// one side, what it owes on the other, and the net result = owned - owed.
// Read-only; every figure comes from GET /api/dashboard/financial-position/
// (backend apps/reports/services/financial_position.py) - nothing is
// recomputed here. Not the Fond de roulement (which adds open debts).
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppAlert from '@/components/ui/AppAlert.vue'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import azurEnergieIcon from '@/assets/azur-energie-icon.png'
import { usePrintScope } from '@/composables/usePrintScope'
import { formatMoney } from '@/utils/currency'
import { exportFinancialPositionPdf, fetchFinancialPosition } from './api'
import type { FinancialPosition, FinancialPositionChild, FinancialPositionLine } from './types'

const { t, te, locale } = useI18n()

const position = ref<FinancialPosition | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    position.value = await fetchFinancialPosition()
  } catch {
    error.value = t('finance.position.loadError')
  } finally {
    loading.value = false
  }
})

function originLabel(key: string): string {
  const path = `finance.position.origins.${key}`
  return te(path) ? t(path) : key
}

function childLabel(child: FinancialPositionChild): string {
  return child.label ?? t(`finance.position.children.${child.key}`)
}

// A sub-line at zero adds nothing to read (an empty fee bucket, an account at 0).
function visibleChildren(line: FinancialPositionLine): FinancialPositionChild[] {
  return line.children.filter((child) => Number(child.amount) !== 0)
}

// PDF (same masthead as the other PDFs) and print (only the page content, with
// a print-only logo header - usePrintScope hides the shell, as in Reports).
const exportingPdf = ref(false)
async function onExportPdf() {
  exportingPdf.value = true
  error.value = ''
  try {
    await exportFinancialPositionPdf(locale.value)
  } catch {
    error.value = t('finance.position.exportError')
  } finally {
    exportingPdf.value = false
  }
}

const pageEl = ref<HTMLElement | null>(null)
const { print: printPage } = usePrintScope(pageEl, ref('portrait'))
const today = new Date().toLocaleDateString(locale.value)

const net = computed(() => (position.value ? Number(position.value.net_result) : 0))

const sides = computed(() =>
  position.value
    ? [
        {
          key: 'assets',
          title: t('finance.position.assets'),
          totalLabel: t('finance.position.totalAssets'),
          side: position.value.assets,
        },
        {
          key: 'liabilities',
          title: t('finance.position.liabilities'),
          totalLabel: t('finance.position.totalLiabilities'),
          side: position.value.liabilities,
        },
      ]
    : [],
)
</script>

<template>
  <div ref="pageEl" class="max-w-5xl space-y-6">
    <!-- Print only: logo + company, like the report sheets. -->
    <div class="hidden items-center gap-4 print:flex" data-test="position-print-masthead">
      <img :src="azurEnergieIcon" alt="" class="size-16 shrink-0" />
      <div>
        <p class="text-2xl font-semibold">AZUR ÉNERGIE</p>
        <p class="text-texte-3 text-sm">{{ today }}</p>
      </div>
    </div>

    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="font-display text-2xl leading-none font-semibold uppercase">
          {{ t('finance.position.title') }}
        </h1>
        <p class="text-texte-2 no-print mt-2 text-sm">{{ t('finance.position.subtitle') }}</p>
      </div>
      <div v-if="position" class="no-print flex gap-2">
        <Button variant="ghost" data-test="position-print" @click="printPage">
          {{ t('reports.print') }}
        </Button>
        <Button
          variant="ghost"
          :disabled="exportingPdf"
          data-test="position-export-pdf"
          @click="onExportPdf"
        >
          {{ t('reports.exportPdf') }}
        </Button>
      </div>
    </div>

    <AppAlert v-if="error" :message="error" />
    <p v-else-if="loading" class="text-sm text-slate-400">{{ t('common.loading') }}</p>

    <template v-else-if="position">
      <div class="grid gap-4 md:grid-cols-2">
        <section
          v-for="block in sides"
          :key="block.key"
          :data-test="`position-${block.key}`"
          class="border-ligne flex flex-col overflow-hidden rounded-xl border bg-white"
        >
          <h2
            class="font-display border-ligne border-b px-4 py-3 text-base font-semibold uppercase"
          >
            {{ block.title }}
          </h2>
          <ul class="flex-1 divide-y divide-[var(--color-ligne,#e5e0d8)]">
            <li v-for="line in block.side.lines" :key="line.key" class="px-4 py-2.5">
              <div class="flex items-baseline justify-between gap-3">
                <span class="text-texte text-sm">{{
                  t(`finance.position.lines.${line.key}`)
                }}</span>
                <MonoValue class="text-sm font-medium" :value="formatMoney(line.amount)" />
              </div>
              <ul v-if="visibleChildren(line).length" class="mt-1 space-y-0.5">
                <li
                  v-for="(child, index) in visibleChildren(line)"
                  :key="index"
                  class="text-texte-3 flex items-baseline justify-between gap-3 ps-4 text-xs"
                >
                  <span>{{ childLabel(child) }}</span>
                  <MonoValue :value="formatMoney(child.amount)" />
                </li>
              </ul>
            </li>
          </ul>
          <div class="bg-bitume text-sable flex items-baseline justify-between gap-3 px-4 py-3">
            <span class="text-sm font-semibold">{{ block.totalLabel }}</span>
            <MonoValue class="text-base font-semibold" :value="formatMoney(block.side.total)" />
          </div>
        </section>
      </div>

      <section
        data-test="position-net-result"
        class="border-ligne flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-white p-5"
      >
        <div>
          <h2 class="font-display text-base font-semibold uppercase">
            {{ t('finance.position.netResult') }}
          </h2>
          <p class="text-texte-3 no-print mt-1 text-xs">{{ t('finance.position.netHelp') }}</p>
        </div>
        <MonoValue
          class="text-[30px] leading-none font-semibold"
          :class="net < 0 ? 'text-critique' : 'text-livre'"
          :value="(net < 0 ? '−' : '') + formatMoney(Math.abs(net))"
        />
      </section>

      <section
        data-test="position-control"
        class="border-ligne space-y-1 rounded-xl border bg-white p-4 text-sm"
      >
        <div class="flex items-baseline justify-between gap-3">
          <span class="text-texte-2">{{ t('finance.position.control') }}</span>
          <MonoValue class="font-medium" :value="formatMoney(position.distributable_result)" />
        </div>
        <div
          v-if="Number(position.starting_funds) !== 0"
          class="flex items-baseline justify-between gap-3"
        >
          <span class="text-texte-2">+ {{ t('finance.position.lines.starting_funds') }}</span>
          <MonoValue class="font-medium" :value="formatMoney(position.starting_funds)" />
        </div>
        <p v-if="Number(position.gap) === 0" class="text-livre text-xs">
          ✓ {{ t('finance.position.controlOk') }}
        </p>
        <p v-else class="text-critique text-xs">
          {{ t('finance.position.controlGap') }} :
          <MonoValue :value="formatMoney(position.gap)" />
        </p>
      </section>

      <p class="text-texte-3 no-print text-xs">{{ t('finance.position.note') }}</p>

      <section class="no-print border-ligne space-y-1 rounded-xl border bg-white p-4 text-sm">
        <div class="flex items-baseline justify-between gap-3">
          <span class="text-texte-2">{{ t('finance.position.fdr') }}</span>
          <MonoValue class="font-medium" :value="formatMoney(position.working_capital_total)" />
        </div>
        <p class="text-texte-3 text-xs">{{ t('finance.position.fdrHelp') }}</p>
      </section>

      <details
        data-test="position-origins"
        class="no-print border-ligne rounded-xl border bg-white p-4 text-sm"
      >
        <summary class="text-texte-2 cursor-pointer font-medium">
          {{ t('finance.position.originsTitle') }}
        </summary>
        <p class="text-texte-3 mt-2 text-xs">{{ t('finance.position.originsHelp') }}</p>
        <ul class="mt-2 space-y-1">
          <li
            v-for="origin in position.treasury_origins"
            :key="origin.key"
            class="flex items-baseline justify-between gap-3"
          >
            <span>{{ originLabel(origin.key) }}</span>
            <MonoValue :value="formatMoney(origin.amount)" />
          </li>
        </ul>
      </details>

      <p class="text-texte-3 text-xs">
        {{ t('finance.position.capital') }} :
        <MonoValue :value="formatMoney(position.capital)" />
      </p>
    </template>
  </div>
</template>
