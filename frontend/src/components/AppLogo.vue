<script setup lang="ts">
/**
 * Marque AZUR ÉNERGIE : monogramme AE + goutte (asset PNG transparent
 * recadré depuis le logo fourni - voir frontend/src/assets/
 * azur-energie-icon.png) accompagné, en option, du wordmark.
 *
 * Le monogramme est bleu foncé/or : sur fond sombre (`tone="light"`) il est
 * posé sur une pastille blanche pour rester lisible ; le texte du wordmark
 * suit aussi `tone`.
 */
import azurEnergieIcon from '@/assets/azur-energie-icon.png'

withDefaults(
  defineProps<{
    size?: number
    wordmark?: boolean
    tone?: 'dark' | 'light'
  }>(),
  {
    size: 32,
    wordmark: true,
    tone: 'dark',
  },
)
</script>

<template>
  <div class="inline-flex items-center gap-2.5">
    <img
      :src="azurEnergieIcon"
      :width="size"
      :height="size"
      alt=""
      aria-hidden="true"
      class="shrink-0 object-contain"
      :class="tone === 'light' ? 'rounded-lg bg-white p-0.5' : ''"
      :style="{ width: `${size}px`, height: `${size}px` }"
    />

    <span
      v-if="wordmark"
      class="font-display text-lg leading-none font-semibold tracking-wide uppercase"
      :class="tone === 'light' ? 'text-sable' : 'text-texte'"
    >
      AZUR ÉNERGIE
    </span>
  </div>
</template>
