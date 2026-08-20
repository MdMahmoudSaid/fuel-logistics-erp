<script setup lang="ts">
defineOptions({ name: 'UiMonoValue' })

/**
 * §0.3 : tout chiffre (litres, MRU/EUR, plaque, ID trajet) s'affiche en
 * IBM Plex Mono avec chiffres tabulaires, aligné à droite dans les tableaux.
 */
withDefaults(
  defineProps<{
    value: string | number
    unit?: string
    align?: 'right' | 'left'
  }>(),
  {
    unit: undefined,
    align: 'right',
  },
)
</script>

<template>
  <span class="font-mono tabular-nums" :class="align === 'right' ? 'text-right' : 'text-left'">
    {{ value }}<span v-if="unit" class="text-texte-2 ml-1">{{ unit }}</span>
  </span>
</template>
