<script setup lang="ts">
/**
 * Marque "Jauge" : un cadran de jauge à essence stylisé (badge bitume,
 * arc + aiguille orange) accompagné, en option, du wordmark.
 *
 * L'orange ne sert ici qu'à la marque (règle §0.1) — jamais comme indicateur
 * de statut. Le badge est autonome (fond bitume propre) pour rester lisible
 * sur fond clair ou sombre ; seul le texte du wordmark suit `tone`.
 */
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
    <svg
      :width="size"
      :height="size"
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect width="32" height="32" rx="8" class="fill-bitume" />
      <path
        d="M9 21a7 7 0 1 1 14 0"
        stroke="var(--orange)"
        stroke-width="2.25"
        stroke-linecap="round"
        stroke-dasharray="1.5 3.4"
      />
      <circle cx="16" cy="21" r="1.6" class="fill-orange" />
      <line
        x1="16"
        y1="21"
        x2="20.2"
        y2="16.4"
        stroke="var(--orange)"
        stroke-width="2.25"
        stroke-linecap="round"
      />
    </svg>

    <span
      v-if="wordmark"
      class="font-display text-lg leading-none font-semibold tracking-wide uppercase"
      :class="tone === 'light' ? 'text-sable' : 'text-texte'"
    >
      Fuel Logistics<span :class="tone === 'light' ? 'text-orange' : 'text-orange-fonce'">.</span>
    </span>
  </div>
</template>
