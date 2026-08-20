<script setup lang="ts">
defineOptions({ name: 'UiGaugeBar' })

/**
 * Jauge/barre de progression — brique de base du design system « Jauge ».
 * `tone` contrôle la couleur de remplissage : `orange` (marque/action,
 * réservé aux jauges neutres de progression) ou l'un des 4 statuts.
 * L'orange n'est jamais utilisé pour représenter un écart/problème (§0.1) —
 * dans ce cas, passer `tone="critique"` ou `tone="ecart"`.
 */
const props = withDefaults(
  defineProps<{
    value: number // 0-100
    tone?: 'orange' | 'livre' | 'transit' | 'ecart' | 'critique'
    label?: string
  }>(),
  {
    tone: 'orange',
    label: undefined,
  },
)

const TONE_CLASSES: Record<string, string> = {
  orange: 'bg-orange',
  livre: 'bg-livre',
  transit: 'bg-transit',
  ecart: 'bg-ecart',
  critique: 'bg-critique',
}

const clamped = () => Math.min(100, Math.max(0, props.value))
</script>

<template>
  <div class="w-full">
    <div v-if="label" class="text-texte-2 mb-1 flex items-center justify-between text-xs">
      <span>{{ label }}</span>
      <span class="font-mono tabular-nums">{{ Math.round(clamped()) }}%</span>
    </div>
    <div
      class="bg-ligne h-1.5 w-full overflow-hidden rounded-full"
      role="progressbar"
      :aria-valuenow="Math.round(clamped())"
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <div
        class="h-full rounded-full transition-[width]"
        :class="TONE_CLASSES[tone]"
        :style="{ width: clamped() + '%' }"
      />
    </div>
  </div>
</template>
