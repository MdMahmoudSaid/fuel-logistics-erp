<script setup lang="ts">
defineOptions({ name: 'UiChip' })

/**
 * Puce de filtre rapide (défilement horizontal sur mobile). L'état actif
 * utilise l'orange — « actif » est un usage explicitement autorisé de la
 * marque au même titre que le bouton primaire et le logo (§1, tokens.css).
 */
withDefaults(
  defineProps<{
    active?: boolean
  }>(),
  {
    active: false,
  },
)

defineEmits<{ click: [] }>()
</script>

<template>
  <button
    type="button"
    class="border-ligne-forte text-texte-2 inline-flex h-9 shrink-0 items-center rounded-full border px-3.5 text-sm whitespace-nowrap transition"
    :class="
      active
        ? 'border-orange bg-orange-tint text-orange-fonce font-medium'
        : 'hover:bg-sable bg-white'
    "
    @click="$emit('click')"
  >
    <slot />
  </button>
</template>
