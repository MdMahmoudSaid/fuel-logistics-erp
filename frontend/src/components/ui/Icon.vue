<script setup lang="ts">
defineOptions({ name: 'UiIcon' })

/**
 * Small hand-drawn outline icon set (24x24, stroke = currentColor) used to
 * add descriptive icons to KPI/action cards without pulling in an icon
 * library dependency (none exists in this project yet).
 */
export type IconName =
  | 'trending-up'
  | 'chart-no-axes-combined'
  | 'wallet'
  | 'receipt'
  | 'receipt-text'
  | 'coins'
  | 'circle-dollar-sign'
  | 'landmark'
  | 'users'
  | 'package'
  | 'truck'
  | 'pie-chart'
  | 'shield'
  | 'shield-check'
  | 'droplet'
  | 'fuel'
  | 'cart-plus'
  | 'file-signature'
  | 'file-text'
  | 'route'
  | 'credit-card'
  | 'banknote'
  | 'more-horizontal'
  | 'eye'
  | 'eye-off'

withDefaults(defineProps<{ name: IconName; size?: number }>(), { size: 20 })
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <g v-if="name === 'trending-up'">
      <polyline points="3 17 9 11 13 15 21 7" />
      <polyline points="15 7 21 7 21 13" />
    </g>
    <g v-else-if="name === 'chart-no-axes-combined'">
      <path d="M4 19V5" />
      <path d="M4 19h16" />
      <path d="M7 15l3-3 3 2 5-7" />
      <path d="M15 7h3v3" />
    </g>
    <g v-else-if="name === 'wallet'">
      <rect x="3" y="6" width="18" height="13" rx="2" />
      <path d="M3 10h18" />
      <circle cx="17" cy="14.5" r="1.1" fill="currentColor" stroke="none" />
    </g>
    <g v-else-if="name === 'receipt'">
      <path d="M6 2h12v19l-3-2-3 2-3-2-3 2V2Z" />
      <path d="M9 8h6M9 12h6" />
    </g>
    <g v-else-if="name === 'receipt-text'">
      <path d="M6 2h12v20l-3-2-3 2-3-2-3 2V2Z" />
      <path d="M9 7h6M9 11h6M9 15h4" />
    </g>
    <g v-else-if="name === 'coins'">
      <circle cx="9" cy="10" r="5" />
      <circle cx="15" cy="14" r="5" />
    </g>
    <g v-else-if="name === 'circle-dollar-sign'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 6v12" />
      <path d="M15 8.5h-4.5a2 2 0 0 0 0 4H13a2 2 0 0 1 0 4H8.5" />
    </g>
    <g v-else-if="name === 'landmark'">
      <path d="M2 10 12 4l10 6" />
      <path d="M4 21V10M9 21V10M15 21V10M20 21V10" />
      <path d="M3 21h18" />
    </g>
    <g v-else-if="name === 'users'">
      <circle cx="9" cy="8" r="3.25" />
      <path d="M3.5 20a5.5 5.5 0 0 1 11 0" />
      <circle cx="17.5" cy="9" r="2.5" />
      <path d="M15.75 13.5a4.5 4.5 0 0 1 6.25 4.1" />
    </g>
    <g v-else-if="name === 'package'">
      <path d="M3 8.5 12 4l9 4.5-9 4.5-9-4.5Z" />
      <path d="M3 8.5V16l9 4.5 9-4.5V8.5" />
      <path d="M12 13v7.5" />
    </g>
    <g v-else-if="name === 'truck'">
      <rect x="1.5" y="8" width="12.5" height="8" rx="1" />
      <path d="M14 11h4l3 3v2h-7Z" />
      <circle cx="6" cy="18" r="1.75" />
      <circle cx="17.5" cy="18" r="1.75" />
    </g>
    <g v-else-if="name === 'pie-chart'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 3v9l7.8 4.2" />
    </g>
    <g v-else-if="name === 'shield'">
      <path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3Z" />
      <path d="M9 12l2 2 4-4" />
    </g>
    <g v-else-if="name === 'shield-check'">
      <path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3Z" />
      <path d="M9 12l2 2 4-4" />
    </g>
    <g v-else-if="name === 'droplet'">
      <path d="M12 3s6.5 7.4 6.5 11.5a6.5 6.5 0 1 1-13 0C5.5 10.4 12 3 12 3Z" />
    </g>
    <g v-else-if="name === 'fuel'">
      <path d="M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16" />
      <path d="M4 10h12" />
      <path d="M16 7h1.5L20 9.5V17a2 2 0 0 0 4 0v-4.5a2 2 0 0 0-2-2H20" />
      <path d="M3 21h14" />
    </g>
    <g v-else-if="name === 'cart-plus'">
      <circle cx="9" cy="20" r="1.4" />
      <circle cx="18" cy="20" r="1.4" />
      <path d="M2.5 3h2l2.4 12.2a2 2 0 0 0 2 1.6h8.6a2 2 0 0 0 2-1.6L21 8H6" />
      <path d="M15 7v4M13 9h4" />
    </g>
    <g v-else-if="name === 'file-signature'">
      <path d="M8 3h6l4 4v13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
      <path d="M14 3v4h4" />
      <path d="M8 16.5s1-1.2 1.8-1.2 1 1.2 1.8 1.2 1-1.4 1.9-1.4 1.1 1.6 2 1.6" />
    </g>
    <g v-else-if="name === 'file-text'">
      <path d="M8 3h6l4 4v13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
      <path d="M14 3v4h4" />
      <path d="M9 12h6M9 16h6M9 8h2" />
    </g>
    <g v-else-if="name === 'route'">
      <circle cx="5" cy="19" r="2" />
      <circle cx="19" cy="5" r="2" />
      <path d="M7 19h7a4 4 0 0 0 4-4V9a4 4 0 0 0-4-4h-1" />
    </g>
    <g v-else-if="name === 'credit-card'">
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <path d="M2 10h20" />
    </g>
    <g v-else-if="name === 'banknote'">
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <circle cx="12" cy="12" r="2.5" />
      <path d="M6 9v.01M18 15v.01" />
    </g>
    <g v-else-if="name === 'eye'">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
      <circle cx="12" cy="12" r="3" />
    </g>
    <g v-else-if="name === 'eye-off'">
      <path d="M9.9 5.2A9.7 9.7 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.2" />
      <path d="M6.6 6.6C3.8 8.4 2 12 2 12s3.5 7 10 7c1.7 0 3.2-.5 4.5-1.2" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      <path d="M3 3l18 18" />
    </g>
    <g v-else-if="name === 'more-horizontal'">
      <circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </g>
  </svg>
</template>
