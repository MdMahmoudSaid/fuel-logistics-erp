<script setup lang="ts">
defineOptions({ name: 'UiBadge' })

/**
 * §0.1 : aucun badge orange n'existe — l'orange n'est jamais un statut.
 * `variant` est volontairement limité aux 4 statuts du design system plus
 * un neutre ; il n'y a pas de variant "orange" à choisir par erreur.
 */
withDefaults(
  defineProps<{
    variant?: 'livre' | 'transit' | 'ecart' | 'critique' | 'neutre'
  }>(),
  {
    variant: 'neutre',
  },
)

const VARIANT_CLASSES: Record<string, string> = {
  livre: 'bg-livre-tint text-livre-texte',
  transit: 'bg-transit-tint text-transit-texte',
  ecart: 'bg-ecart-tint text-ecart-texte',
  critique: 'bg-critique-tint text-critique-texte',
  neutre: 'bg-sable text-texte-2',
}
</script>

<template>
  <span
    class="inline-flex h-6 shrink-0 items-center whitespace-nowrap rounded-full px-2.5 text-xs font-medium"
    :class="VARIANT_CLASSES[variant]"
  >
    <slot />
  </span>
</template>
