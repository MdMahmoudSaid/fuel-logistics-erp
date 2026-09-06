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
    align?: 'right' | 'left' | 'center'
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
    class="inline-flex items-baseline gap-1 whitespace-nowrap font-mono tabular-nums"
    :class="align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-start'"
  >
    {{ value
    }}<span v-if="unit" class="font-mono text-[0.85em] font-normal text-current">{{
      ' ' + unit
    }}</span>
  </span>
</template>
