<script setup lang="ts">
defineOptions({ name: 'DashboardVolumeTrendChart' })

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { VolumeDay } from './aggregate'

const props = defineProps<{ days: VolumeDay[] }>()

const { t } = useI18n()

const maxValue = computed(() => Math.max(1, ...props.days.map((d) => d.value)))
</script>

<template>
  <div class="border-ligne rounded-xl border bg-white p-4">
    <p class="text-texte-2 mb-4 text-xs font-medium uppercase">
      {{ t('dashboard.volumeTrend') }}
    </p>
    <div class="flex h-32 items-end gap-1.5">
      <div
        v-for="day in days"
        :key="day.date"
        class="group flex flex-1 flex-col items-center gap-1.5"
        :title="`${day.date} — ${Math.round(day.value).toLocaleString()} L`"
      >
        <div class="flex h-24 w-full items-end">
          <div
            class="w-full rounded-t transition-[height]"
            :class="day.isToday ? 'bg-orange' : 'bg-bitume group-hover:bg-bitume-2'"
            :style="{ height: (day.value / maxValue) * 100 + '%' }"
          />
        </div>
        <span class="text-texte-3 font-mono text-[10px] tabular-nums">{{ day.dayLabel }}</span>
      </div>
    </div>
  </div>
</template>
