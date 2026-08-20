<script setup lang="ts">
// Shared date-range filter (docs/PHASE_6_PLAN.md Etape 7): predefined
// periods plus a custom from/to pair, emitting the same shape the backend
// dashboard/report endpoints already accept (?range=|&from=&to=).
import { ref, onMounted } from 'vue'
import type { DateRangeValue } from './date-range'

const PRESETS = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'week', label: 'This week' },
  { value: 'month', label: 'This month' },
  { value: 'year', label: 'This year' },
  { value: 'custom', label: 'Custom period' },
] as const

const emit = defineEmits<{ change: [DateRangeValue] }>()

const selected = ref<string>('month')
const from = ref('')
const to = ref('')

function apply() {
  if (selected.value === 'custom') {
    emit('change', { from: from.value || undefined, to: to.value || undefined })
  } else {
    emit('change', { range: selected.value })
  }
}

onMounted(apply)
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <select
      v-model="selected"
      class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
      @change="apply"
    >
      <option v-for="preset in PRESETS" :key="preset.value" :value="preset.value">
        {{ preset.label }}
      </option>
    </select>
    <template v-if="selected === 'custom'">
      <input
        v-model="from"
        type="date"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="apply"
      />
      <span class="text-texte-3">→</span>
      <input
        v-model="to"
        type="date"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="apply"
      />
    </template>
  </div>
</template>
