<script setup lang="ts">
defineOptions({ name: 'UiButton' })

/**
 * §0.1/§0.2 : le variant `primary` est le SEUL à porter le fond orange, et
 * son texte reste toujours foncé (--bitume) — jamais blanc sur orange.
 * `size="field"` couvre la zone tactile 56px exigée pour les actions
 * terrain (validation de livraison, saisie de jauge) — §0.4.
 */
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'md' | 'field'
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
    loading?: boolean
  }>(),
  {
    variant: 'primary',
    size: 'md',
    type: 'button',
    disabled: false,
    loading: false,
  },
)

const VARIANT_CLASSES: Record<string, string> = {
  primary: 'bg-orange text-bitume hover:brightness-95 focus-visible:outline-bitume',
  secondary: 'bg-bitume text-sable hover:bg-bitume-2 focus-visible:outline-bitume',
  ghost:
    'bg-transparent text-texte border border-ligne-forte hover:bg-sable focus-visible:outline-bitume',
  danger: 'bg-critique text-white hover:brightness-95 focus-visible:outline-critique',
}

const SIZE_CLASSES: Record<string, string> = {
  md: 'h-12 px-4 text-sm',
  field: 'h-14 px-5 text-base',
}
</script>

<template>
  <button
    :type="type"
    :disabled="disabled || loading"
    class="inline-flex items-center justify-center gap-2 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
    :class="[VARIANT_CLASSES[variant], SIZE_CLASSES[size]]"
  >
    <slot />
  </button>
</template>
