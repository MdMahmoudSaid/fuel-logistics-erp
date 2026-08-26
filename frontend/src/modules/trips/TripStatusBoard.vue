<script setup lang="ts">
// Vue hybride (docs/UI_REDESIGN_PLAN.md Etape 6.2) : tableau desktop
// (>=768px, chiffres Mono alignés à droite) / liste de TripCard mobile
// (<768px), avec puces de filtre statut à défilement horizontal.
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { tripResource } from './api'
import { TRIP_STATUSES } from './types'
import type { Trip, TripStatus } from './types'
import Chip from '@/components/ui/Chip.vue'
import Badge from '@/components/ui/Badge.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import Button from '@/components/ui/Button.vue'
import TripCard from './TripCard.vue'
import { useTripStatusLabel } from './tripStatusLabels'

const router = useRouter()
const { t } = useI18n()
const statusLabel = useTripStatusLabel()

const trips = ref<Trip[]>([])
const loading = ref(false)
const error = ref('')

// Cette vue couvre les opérations "en cours d'exécution" (plan Etape 9) -
// les trajets livrés/annulés ont leur propre historique (TripDetail, listes
// camion/commande) plutôt que de s'accumuler ici indéfiniment.
const FILTER_STATUSES: TripStatus[] = TRIP_STATUSES.filter(
  (s) => s !== 'COMPLETED' && s !== 'CANCELLED',
)

const selectedStatus = ref<TripStatus | ''>('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    // NB: une seule page (25, PAGE_SIZE) de /api/trips/ - même convention
    // que SupplierOrderList/CustomerOrderList. Correct tant que le volume de
    // trajets actifs reste modeste.
    const data = await tripResource.list()
    trips.value = data.results
  } catch {
    error.value = t('trips.loadError')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const filteredTrips = computed(() => {
  if (selectedStatus.value) return trips.value.filter((t) => t.status === selectedStatus.value)
  return trips.value.filter((t) => FILTER_STATUSES.includes(t.status))
})

const badgeVariant = (status: TripStatus) => {
  if (status === 'DELIVERED' || status === 'COMPLETED') return 'livre' as const
  if (status === 'BLOCKED' || status === 'CANCELLED') return 'critique' as const
  return 'transit' as const
}

function goToDetail(trip: Trip) {
  router.push({ name: 'trip-detail', params: { id: trip.id } })
}

function goToNew() {
  router.push({ name: 'trip-new' })
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('trips.title') }}
      </h1>
      <Button variant="primary" @click="goToNew">{{ t('trips.newTrip') }}</Button>
    </div>

    <div class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      <Chip :active="selectedStatus === ''" @click="selectedStatus = ''">{{ t('trips.all') }}</Chip>
      <Chip
        v-for="status in FILTER_STATUSES"
        :key="status"
        :active="selectedStatus === status"
        @click="selectedStatus = selectedStatus === status ? '' : status"
      >
        {{ statusLabel(status) }}
      </Chip>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else>
      <!-- Desktop : tableau complet, chiffres Mono alignés à droite -->
      <div class="border-ligne hidden overflow-x-auto rounded-xl border bg-white md:block">
        <table class="w-full text-left text-sm">
          <thead>
            <tr class="border-ligne text-texte-2 border-b">
              <th class="px-3 py-2.5 font-medium">{{ t('trips.table.reference') }}</th>
              <th class="px-3 py-2.5 font-medium">{{ t('trips.table.truck') }}</th>
              <th class="px-3 py-2.5 font-medium">{{ t('trips.table.transporter') }}</th>
              <th class="px-3 py-2.5 font-medium">{{ t('trips.table.client') }}</th>
              <th class="px-3 py-2.5 text-right font-medium">{{ t('trips.table.quantity') }}</th>
              <th class="px-3 py-2.5 font-medium">{{ t('trips.table.status') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="trip in filteredTrips"
              :key="trip.id"
              class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
              @click="goToDetail(trip)"
            >
              <td class="px-3 py-2.5"><MonoValue :value="trip.reference" align="left" /></td>
              <td class="px-3 py-2.5">{{ trip.truck_detail?.internal_id ?? '—' }}</td>
              <td class="px-3 py-2.5">{{ trip.transporter_detail?.name ?? '—' }}</td>
              <td class="px-3 py-2.5">
                {{
                  trip.destination_type === 'COMPANY_STOCK'
                    ? t('trips.detail.companyStock')
                    : (trip.client_detail?.name ?? '—')
                }}
              </td>
              <td class="px-3 py-2.5 text-right">
                <MonoValue :value="Number(trip.quantity_loaded).toLocaleString()" unit="L" />
              </td>
              <td class="px-3 py-2.5">
                <Badge :variant="badgeVariant(trip.status)">{{ statusLabel(trip.status) }}</Badge>
              </td>
            </tr>
            <tr v-if="!filteredTrips.length">
              <td colspan="6" class="text-texte-3 px-3 py-8 text-center">
                {{ t('trips.noTripsForFilter') }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Mobile : liste de TripCard empilées -->
      <div class="space-y-3 md:hidden">
        <TripCard v-for="trip in filteredTrips" :key="trip.id" :trip="trip" />
        <p
          v-if="!filteredTrips.length"
          class="text-texte-3 border-ligne rounded-xl border border-dashed p-6 text-center text-sm"
        >
          {{ t('trips.noTripsForFilter') }}
        </p>
      </div>
    </template>
  </div>
</template>
