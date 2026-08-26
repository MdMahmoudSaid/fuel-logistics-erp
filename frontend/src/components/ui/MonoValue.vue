<script setup lang="ts">
defineOptions({ name: 'UiMonoValue' })

/**
 * §0.3 : tout chiffre (litres, XOF, plaque, ID trajet) s'affiche en
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
  <span
    dir="ltr"
    class="font-mono tabular-nums"
    :class="align === 'right' ? 'text-right' : 'text-start'"
  >
    {{ value }}<span v-if="unit" class="text-texte-2 ms-1">{{ unit }}</span>
  </span>
</template>
