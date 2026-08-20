<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    maxWidth?: string
  }>(),
  { maxWidth: 'max-w-lg' },
)
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div
    class="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4"
    @click.self="emit('close')"
  >
    <div
      class="bg-surface border-ligne w-full space-y-4 rounded-xl border p-6"
      :class="[maxWidth, 'max-h-[90vh] overflow-y-auto']"
      role="dialog"
      aria-modal="true"
    >
      <div class="flex items-center justify-between">
        <h2 class="font-display text-lg leading-none font-semibold uppercase">{{ title }}</h2>
        <button
          type="button"
          class="text-texte-2 hover:text-texte flex h-8 w-8 items-center justify-center rounded-lg text-xl leading-none"
          :aria-label="$t('common.close')"
          @click="emit('close')"
        >
          &times;
        </button>
      </div>
      <slot />
    </div>
  </div>
</template>
