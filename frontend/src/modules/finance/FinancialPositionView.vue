<script setup lang="ts">
// "Situation financiere" (client request 2026-10-17): what the company owns on
// one side, what it owes on the other, and the net result = owned - owed.
// Read-only; every figure comes from GET /api/dashboard/financial-position/
// (backend apps/reports/services/financial_position.py) - nothing is
// recomputed here. Not the Fond de roulement (which adds open debts).
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppAlert from '@/components/ui/AppAlert.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { formatMoney } from '@/utils/currency'
import { fetchFinancialPosition } from './api'
import type { FinancialPosition, FinancialPositionChild, FinancialPositionLine } from './types'

const { t } = useI18n()

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

function childLabel(child: FinancialPositionChild): string {
  return child.label ?? t(`finance.position.children.${child.key}`)
}

// A sub-line at zero adds nothing to read (an empty fee bucket, an account at 0).
function visibleChildren(line: FinancialPositionLine): FinancialPositionChild[] {
  return line.children.filter((child) => Number(child.amount) !== 0)
}

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
  <div class="max-w-5xl space-y-6">
    <div>
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('finance.position.title') }}
      </h1>
      <p class="text-texte-2 mt-2 text-sm">{{ t('finance.position.subtitle') }}</p>
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
          <p class="text-texte-3 mt-1 text-xs">{{ t('finance.position.netHelp') }}</p>
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
        <p v-if="Number(position.gap) === 0" class="text-livre text-xs">
          ✓ {{ t('finance.position.controlOk') }}
        </p>
        <p v-else class="text-critique text-xs">
          {{ t('finance.position.controlGap') }} :
          <MonoValue :value="formatMoney(position.gap)" />
        </p>
      </section>

      <p class="text-texte-3 text-xs">{{ t('finance.position.note') }}</p>
      <p v-if="Number(position.matched_unsold) !== 0" class="text-texte-3 text-xs">
        {{ t('finance.position.matchedNote') }}
        <MonoValue :value="formatMoney(position.matched_unsold)" />
      </p>

      <p class="text-texte-3 text-xs">
        {{ t('finance.position.capital') }} :
        <MonoValue :value="formatMoney(position.capital)" />
      </p>
    </template>
  </div>
</template>
