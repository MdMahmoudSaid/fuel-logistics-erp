<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// Vue hybride (docs/UI_REDESIGN_PLAN.md Etape 6.2) : tableau desktop
// (>=768px, chiffres Mono alignés à droite) / liste de TripCard mobile
// (<768px), avec puces de filtre statut à défilement horizontal.
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { tripResource } from './api'
import type { Trip, TripStatus } from './types'
import Chip from '@/components/ui/Chip.vue'
import Badge from '@/components/ui/Badge.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import Button from '@/components/ui/Button.vue'
import TripCard from './TripCard.vue'
import { useTripStatusLabel } from './tripStatusLabels'
import { formatTruckPlates } from './formatTruckPlates'
import { formatQuantity } from '@/utils/currency'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const statusLabel = useTripStatusLabel()

const trips = ref<Trip[]>([])
const loading = ref(false)
const error = ref('')

// Cette vue couvre les opérations "en cours d'exécution" (plan Etape 9) -
// les trajets livrés/annulés ont leur propre historique (TripDetail, listes
// camion/commande) plutôt que de s'accumuler ici indéfiniment.
type BusinessFilter =
  | 'all'
  | 'in-progress'
  | 'company-stock'
  | 'to-deliver'
  | 'to-control'
  | 'delivered'
  | 'cancelled'

const BUSINESS_FILTERS: { key: BusinessFilter; label: string }[] = [
  { key: 'all', label: 'Tous' },
  { key: 'in-progress', label: 'En cours' },
  { key: 'company-stock', label: 'Stock entreprise' },
  { key: 'to-deliver', label: 'À livrer' },
  { key: 'to-control', label: 'À contrôler' },
  { key: 'delivered', label: 'Livrés' },
  // Bug fix (2026-09-03 recette manuelle): cancelled trips were previously
  // only reachable by excluding them from "Tous" - there was no way to
  // actually consult them. "Tous" stays active-trips-only (unchanged
  // semantics, see filteredTrips below); this is their own, separate tab.
  { key: 'cancelled', label: 'Annulés' },
]

function filterFromRoute(): BusinessFilter {
  return route.name === 'company-stock' || route.query.filter === 'company-stock'
    ? 'company-stock'
    : 'all'
}

const selectedFilter = ref<BusinessFilter>(filterFromRoute())

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

watch(
  () => [route.name, route.query.filter],
  async () => {
    selectedFilter.value = filterFromRoute()
    await load()
  },
)

const filteredTrips = computed(() => {
  if (selectedFilter.value === 'company-stock') {
    // Only trips that have physically arrived at the depot - matches the
    // dashboard's "Stock de l'entreprise" total (backend
    // reports/views/dashboard.py). Earlier pipeline statuses (LOADING,
    // IN_TRANSIT, GOING_TO_COMPANY_STOCK...) haven't arrived yet, and a trip
    // un-assigned from a customer keeps its old status (QUANTITY_CONTROL,
    // DELIVERED...) even once destination_type flips back to COMPANY_STOCK -
    // counting either here would make this list disagree with the number
    // the user came from.
    return trips.value.filter(
      (t) =>
        t.destination_type === 'COMPANY_STOCK' &&
        (t.status === 'ARRIVED_AT_COMPANY_STOCK' || t.status === 'STOCKED'),
    )
  }
  if (selectedFilter.value === 'in-progress') {
    return trips.value.filter((t) =>
      [
        'ASSIGNED',
        'SENT_FOR_LOADING',
        'LOADING',
        'LOADED',
        'ROAD_TRANSIT',
        'IN_TRANSIT',
        'BORDER',
        'CUSTOMS',
      ].includes(t.status),
    )
  }
  if (selectedFilter.value === 'to-deliver') {
    return trips.value.filter((t) => ['GOING_TO_CLIENT', 'ARRIVED_AT_CLIENT'].includes(t.status))
  }
  if (selectedFilter.value === 'to-control') {
    return trips.value.filter((t) => t.status === 'QUANTITY_CONTROL' || t.status === 'BLOCKED')
  }
  if (selectedFilter.value === 'delivered') {
    return trips.value.filter((t) => ['DELIVERED', 'COMPLETED'].includes(t.status))
  }
  if (selectedFilter.value === 'cancelled') {
    return trips.value.filter((t) => t.status === 'CANCELLED')
  }
  return trips.value.filter((t) => t.status !== 'CANCELLED')
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

function nextAction(trip: Trip) {
  if (trip.destination_type === 'COMPANY_STOCK' && !trip.client) return 'Attribuer à un client'
  if (trip.status === 'QUANTITY_CONTROL') return 'Contrôler la quantité'
  if (trip.status === 'BLOCKED') return 'Débloquer / corriger'
  if (trip.status === 'ARRIVED_AT_CLIENT') return 'Valider la livraison'
  return 'Voir détail'
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('trips.title') }}
      </h1>
      <Button variant="primary" @click="goToNew">{{ t('trips.newTrip') }}</Button>
    </div>

    <div class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      <Chip
        v-for="filter in BUSINESS_FILTERS"
        :key="filter.key"
        :active="selectedFilter === filter.key"
        @click="selectedFilter = filter.key"
      >
        {{ filter.label }}
      </Chip>
    </div>

    <AppAlert v-if="error" :message="error" />
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
              <th class="px-3 py-2.5 font-medium">Fournisseur</th>
              <th class="px-3 py-2.5 font-medium">{{ t('trips.table.cessionLetter') }}</th>
              <th class="px-3 py-2.5 font-medium">{{ t('trips.table.client') }}</th>
              <th class="px-3 py-2.5 font-medium">Produit</th>
              <th class="px-3 py-2.5 text-right font-medium">{{ t('trips.table.quantity') }}</th>
              <th class="px-3 py-2.5 font-medium">{{ t('trips.table.status') }}</th>
              <th class="px-3 py-2.5 font-medium">Prochaine action</th>
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
              <td class="px-3 py-2.5">{{ formatTruckPlates(trip.truck_detail) }}</td>
              <td class="px-3 py-2.5">{{ trip.transporter_detail?.name ?? '—' }}</td>
              <td class="px-3 py-2.5">{{ trip.supplier_detail?.name ?? '—' }}</td>
              <td class="px-3 py-2.5">
                <div v-if="trip.cession_letter_detail">
                  <MonoValue :value="trip.cession_letter_detail.reference" align="left" />
                  <p class="text-texte-3 text-xs">
                    {{
                      t('trips.table.cessionLetterLoadCount', {
                        count: trip.cession_letter_truck_load_count,
                      })
                    }}
                  </p>
                </div>
                <span v-else>—</span>
              </td>
              <td class="px-3 py-2.5">
                {{
                  trip.destination_type === 'COMPANY_STOCK'
                    ? t('trips.detail.companyStock')
                    : (trip.client_detail?.name ?? '—')
                }}
              </td>
              <td class="px-3 py-2.5">{{ trip.product_detail?.name ?? '—' }}</td>
              <td class="px-3 py-2.5 text-right">
                <MonoValue :value="formatQuantity(trip.quantity_loaded)" />
              </td>
              <td class="px-3 py-2.5">
                <Badge :variant="badgeVariant(trip.status)">{{ statusLabel(trip.status) }}</Badge>
              </td>
              <td class="px-3 py-2.5">{{ nextAction(trip) }}</td>
            </tr>
            <tr v-if="!filteredTrips.length">
              <td colspan="10" class="text-texte-3 px-3 py-8 text-center">
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
