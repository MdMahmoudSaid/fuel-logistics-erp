<script setup lang="ts">
defineOptions({ name: 'UiCard' })

withDefaults(
  defineProps<{
    title?: string
  }>(),
  { title: undefined },
)
</script>

<template>
  <div class="border-ligne rounded-xl border bg-white">
    <div
      v-if="title || $slots.actions"
      class="border-ligne flex items-center justify-between border-b px-5 py-4"
    >
      <h2 v-if="title" class="font-display text-lg leading-none font-semibold uppercase">
        {{ title }}
      </h2>
      <div v-if="$slots.actions"><slot name="actions" /></div>
    </div>
    <div class="p-5">
      <slot />
    </div>
  </div>
</template>
