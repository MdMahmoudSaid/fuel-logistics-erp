<script setup lang="ts">
/**
 * Marque de ce build (nom + icône, voir frontend/brands/ et src/brand.ts) :
 * icône PNG transparente accompagnée, en option, du wordmark.
 *
 * L'icône peut être sombre : sur fond sombre (`tone="light"`) il est
 * posé sur une pastille blanche pour rester lisible ; le texte du wordmark
 * suit aussi `tone`.
 */
import { BRAND_ICON, BRAND_NAME } from '@/brand'

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
      :src="BRAND_ICON"
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
      {{ BRAND_NAME }}
    </span>
  </div>
</template>
