<script setup lang="ts">
defineOptions({ name: 'DashboardKpiTile' })

import GaugeBar from '@/components/ui/GaugeBar.vue'

withDefaults(
  defineProps<{
    label: string
    value: string
    unit?: string
    gaugeValue: number
    gaugeTone?: 'orange' | 'livre' | 'transit' | 'ecart' | 'critique'
  }>(),
  {
    unit: undefined,
    gaugeTone: 'orange',
  },
)
</script>

<template>
  <div class="border-ligne space-y-3 rounded-xl border bg-white p-4">
    <p class="text-texte-2 text-xs font-medium uppercase">{{ label }}</p>
    <p class="font-mono text-2xl leading-none font-semibold tabular-nums">
      {{ value
      }}<span v-if="unit" class="text-texte-2 font-sans text-sm font-normal">{{
        ' ' + unit
      }}</span>
    </p>
    <GaugeBar :value="gaugeValue" :tone="gaugeTone" />
  </div>
</template>
