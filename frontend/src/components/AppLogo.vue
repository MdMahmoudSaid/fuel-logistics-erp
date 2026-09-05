<script setup lang="ts">
/**
 * Marque AZUR ÉNERGIE : icône circulaire (goutte + globe, asset PNG
 * recadré depuis le logo fourni - voir frontend/src/assets/
 * azur-energie-icon.png) accompagnée, en option, du wordmark.
 *
 * L'icône a son propre fond circulaire opaque (bleu/or) et un fond
 * transparent autour, donc elle reste lisible sur fond clair ou sombre
 * sans traitement supplémentaire ; seul le texte du wordmark suit `tone`.
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
