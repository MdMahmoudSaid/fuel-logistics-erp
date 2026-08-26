<script setup lang="ts">
defineOptions({ name: 'TripCard' })

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import GaugeBar from '@/components/ui/GaugeBar.vue'
import UiBadge from '@/components/ui/Badge.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { TRIP_PIPELINE_STATUSES } from './types'
import type { Trip } from './types'
import { useTripStatusLabel } from './tripStatusLabels'
import { formatQuantity } from '@/utils/currency'

const props = defineProps<{ trip: Trip }>()

const { t } = useI18n()
const statusLabel = useTripStatusLabel()

const progress = computed(() => {
  const idx = TRIP_PIPELINE_STATUSES.indexOf(props.trip.status)
  if (idx === -1) return props.trip.status === 'COMPLETED' ? 100 : 0
  return (idx / (TRIP_PIPELINE_STATUSES.length - 1)) * 100
})

const progressTone = computed(() => {
  if (props.trip.status === 'BLOCKED') return 'critique' as const
  if (props.trip.status === 'CANCELLED') return 'ecart' as const
  return 'orange' as const
})

const badgeVariant = computed(() => {
  if (props.trip.status === 'DELIVERED' || props.trip.status === 'COMPLETED') return 'livre'
  if (props.trip.status === 'BLOCKED' || props.trip.status === 'CANCELLED') return 'critique'
  return 'transit'
})
</script>

<template>
  <RouterLink
    :to="{ name: 'trip-detail', params: { id: trip.id } }"
    class="border-ligne block space-y-3 rounded-xl border bg-white p-4 transition hover:border-orange"
  >
    <div class="flex items-start justify-between gap-2">
      <div>
        <p class="font-mono text-sm font-medium">{{ trip.reference }}</p>
        <p class="text-texte-2 text-xs">
          {{ trip.truck_detail?.internal_id }} ·
          {{
            trip.destination_type === 'COMPANY_STOCK'
              ? t('trips.detail.companyStock')
              : (trip.client_detail?.name ?? '—')
          }}
        </p>
      </div>
      <UiBadge :variant="badgeVariant">{{ statusLabel(trip.status) }}</UiBadge>
    </div>

    <div class="flex items-end justify-between gap-2">
      <GaugeBar :value="progress" :tone="progressTone" class="max-w-[65%]" />
      <MonoValue :value="formatQuantity(trip.quantity_loaded)" />
    </div>
  </RouterLink>
</template>
