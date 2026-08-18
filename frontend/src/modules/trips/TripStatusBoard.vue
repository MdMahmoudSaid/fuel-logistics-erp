<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { tripResource } from './api'
import { TRIP_STATUSES } from './types'
import type { Trip, TripStatus } from './types'

const router = useRouter()

const trips = ref<Trip[]>([])
const loading = ref(false)
const error = ref('')

// Kanban shows operations "en cours d'exécution" (plan Etape 9) — completed
// and cancelled trips have their own history views (TripDetail, truck/order
// trip lists) rather than piling up on the board indefinitely.
const BOARD_STATUSES = TRIP_STATUSES.filter((s) => s !== 'COMPLETED' && s !== 'CANCELLED')

const COLUMN_LABEL: Record<TripStatus, string> = {
  ASSIGNED: 'Assigned',
  SENT_FOR_LOADING: 'Sent for loading',
  LOADING: 'Loading',
  LOADED: 'Loaded',
  IN_TRANSIT: 'In transit',
  BORDER: 'Border',
  CUSTOMS: 'Customs',
  GOING_TO_CLIENT: 'Going to client',
  ARRIVED_AT_CLIENT: 'Arrived at client',
  QUANTITY_CONTROL: 'Quantity control',
  DELIVERED: 'Delivered',
  COMPLETED: 'Completed',
  BLOCKED: 'Blocked',
  CANCELLED: 'Cancelled',
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    // NB: this reads a single page (25, PAGE_SIZE) from the paginated
    // /api/trips/ list — same "one page, no follow-the-next-link"
    // convention as SupplierOrderList/CustomerOrderList. Fine while active
    // trip volume stays modest; revisit (server-side page_size override or
    // a dedicated unpaginated board endpoint) if it grows past a page.
    const data = await tripResource.list()
    trips.value = data.results
  } catch {
    error.value = 'Could not load trips.'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const columns = computed(() =>
  BOARD_STATUSES.map((status) => ({
    status,
    label: COLUMN_LABEL[status],
    trips: trips.value.filter((t) => t.status === status),
  })),
)

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
      <h2 class="text-lg font-semibold text-slate-800">Trips &amp; Loading</h2>
      <button
        class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white"
        @click="goToNew"
      >
        New Trip
      </button>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">Loading…</p>

    <div v-else class="flex gap-3 overflow-x-auto pb-2">
      <div
        v-for="column in columns"
        :key="column.status"
        class="w-64 shrink-0 rounded border bg-slate-50"
      >
        <div class="flex items-center justify-between border-b bg-white px-3 py-2">
          <span class="text-sm font-medium text-slate-700">{{ column.label }}</span>
          <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            {{ column.trips.length }}
          </span>
        </div>
        <div class="space-y-2 p-2">
          <button
            v-for="trip in column.trips"
            :key="trip.id"
            class="w-full rounded border bg-white p-2 text-left text-sm shadow-sm hover:border-slate-400"
            @click="goToDetail(trip)"
          >
            <div class="font-medium text-slate-800">{{ trip.reference }}</div>
            <div class="text-xs text-slate-500">{{ trip.truck_detail?.internal_id }}</div>
            <div class="text-xs text-slate-500">
              {{ Number(trip.quantity_loaded).toLocaleString() }} L
            </div>
          </button>
          <p v-if="!column.trips.length" class="px-1 py-2 text-center text-xs text-slate-400">—</p>
        </div>
      </div>
    </div>
  </div>
</template>
