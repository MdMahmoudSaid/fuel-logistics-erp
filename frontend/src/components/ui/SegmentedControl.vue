<script setup lang="ts" generic="T extends string">
// Pill-shaped switch (dark selected pill on a white rounded track), used to
// flip between record groups such as Actifs / Anciens / Inactifs.
defineProps<{
  options: { value: T; label: string; count?: number; testId?: string }[]
  modelValue: T
  ariaLabel?: string
}>()

defineEmits<{ 'update:modelValue': [value: T] }>()
</script>

<template>
  <div
    role="tablist"
    :aria-label="ariaLabel"
    class="border-ligne-forte inline-flex max-w-full gap-1 rounded-xl border bg-white p-1"
  >
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      role="tab"
      :aria-selected="option.value === modelValue"
      :data-test="option.testId"
      class="h-9 rounded-lg px-4 text-sm font-medium whitespace-nowrap transition-colors"
      :class="
        option.value === modelValue
          ? 'bg-bitume text-white'
          : 'text-texte-2 hover:text-texte bg-transparent'
      "
      @click="$emit('update:modelValue', option.value)"
    >
      {{ option.label }}<template v-if="option.count !== undefined"> ({{ option.count }})</template>
    </button>
  </div>
</template>
