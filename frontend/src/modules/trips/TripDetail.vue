<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { tripResource, fetchTripHistory, postTripStatus } from './api'
import DeliveryControlForm from './DeliveryControlForm.vue'
import { TRIP_STATUSES } from './types'
import type { Trip, TripStatusHistoryEntry } from './types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const tripId = computed(() => Number(route.params.id))

const trip = ref<Trip | null>(null)
const history = ref<TripStatusHistoryEntry[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    ;[trip.value, history.value] = await Promise.all([
      tripResource.get!(tripId.value),
      fetchTripHistory(tripId.value),
    ])
  } catch {
    error.value = 'Could not load this trip.'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const canChangeStatus = computed(() => auth.can('operations', 'edit'))

// The backend's TripWorkflowService is the sole authority on which
// transitions are valid from the current status (guide §6.9: "Do not
// hard-code workflow rules in Vue") — every status is offered here and
// whatever the server rejects is surfaced as an error, rather than this
// component re-deriving the transition table.
const nextStatus = ref('')
const statusNotes = ref('')
const changingStatus = ref(false)
const statusError = ref('')

async function onChangeStatus() {
  if (!nextStatus.value) return
  changingStatus.value = true
  statusError.value = ''
  try {
    await postTripStatus(tripId.value, nextStatus.value, statusNotes.value)
    nextStatus.value = ''
    statusNotes.value = ''
    await load()
  } catch (e) {
    const data = (e as { response?: { data?: { detail?: string } } })?.response?.data
    statusError.value = data?.detail || 'Could not change status.'
  } finally {
    changingStatus.value = false
  }
}

const STATUS_BADGE: Record<string, string> = {
  COMPLETED: 'bg-emerald-100 text-emerald-700',
  DELIVERED: 'bg-emerald-100 text-emerald-700',
  CANCELLED: 'bg-red-100 text-red-700',
  BLOCKED: 'bg-red-100 text-red-700',
  ASSIGNED: 'bg-slate-100 text-slate-600',
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString()
}
</script>

<template>
  <div class="max-w-3xl space-y-6">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">Trip {{ trip?.reference ?? '' }}</h2>
      <button class="px-3 py-2 text-sm text-slate-500" @click="router.push({ name: 'trips' })">
        Back to board
      </button>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">Loading…</p>

    <template v-else-if="trip">
      <section class="grid grid-cols-2 gap-4 rounded border bg-white p-4 text-sm">
        <div>
          <span class="text-slate-500">Status</span>
          <p>
            <span
              class="rounded-full px-2 py-0.5 text-xs font-medium"
              :class="STATUS_BADGE[trip.status] ?? 'bg-amber-100 text-amber-700'"
            >
              {{ trip.status }}
            </span>
          </p>
        </div>
        <div>
          <span class="text-slate-500">Truck</span>
          <p class="font-medium text-slate-800">{{ trip.truck_detail?.internal_id }}</p>
        </div>
        <div>
          <span class="text-slate-500">Transporter</span>
          <p class="font-medium text-slate-800">
            <RouterLink
              class="underline decoration-dotted"
              :to="{ name: 'transporter-ledger', params: { id: trip.transporter } }"
            >
              {{ trip.transporter_detail?.name }}
            </RouterLink>
          </p>
        </div>
        <div>
          <span class="text-slate-500">Driver</span>
          <p class="font-medium text-slate-800">{{ trip.driver_detail?.name ?? '—' }}</p>
        </div>
        <div>
          <span class="text-slate-500">Supplier</span>
          <p class="font-medium text-slate-800">{{ trip.supplier_detail?.name }}</p>
        </div>
        <div>
          <span class="text-slate-500">Product</span>
          <p class="font-medium text-slate-800">{{ trip.product_detail?.name }}</p>
        </div>
        <div>
          <span class="text-slate-500">Quantity loaded</span>
          <p class="font-medium text-slate-800">
            {{ Number(trip.quantity_loaded).toLocaleString() }} L
          </p>
        </div>
        <div>
          <span class="text-slate-500">Loading date</span>
          <p class="font-medium text-slate-800">{{ trip.loading_date }}</p>
        </div>
        <div>
          <span class="text-slate-500">BL reference</span>
          <p class="font-medium text-slate-800">{{ trip.bl_reference }}</p>
        </div>
        <div>
          <span class="text-slate-500">Client</span>
          <p class="font-medium text-slate-800">
            {{ trip.client_detail?.name ?? (trip.customer_order ? '—' : 'Direct sale') }}
          </p>
        </div>
        <div v-if="trip.customer_order">
          <span class="text-slate-500">Customer order</span>
          <p>
            <RouterLink
              class="font-medium text-slate-800 underline decoration-dotted"
              :to="{ name: 'customer-order-detail', params: { id: trip.customer_order } }"
            >
              #{{ trip.customer_order }}
            </RouterLink>
          </p>
        </div>
        <div v-if="trip.notes" class="col-span-2">
          <span class="text-slate-500">Notes</span>
          <p class="font-medium text-slate-800">{{ trip.notes }}</p>
        </div>
      </section>

      <section v-if="canChangeStatus" class="space-y-3 rounded border bg-white p-4">
        <h3 class="text-base font-semibold text-slate-800">Change status</h3>
        <p v-if="statusError" class="text-sm text-red-600">{{ statusError }}</p>

        <div class="flex flex-wrap items-end gap-2">
          <div class="space-y-1">
            <label class="text-sm font-medium text-slate-600" for="next_status">Next status</label>
            <select
              id="next_status"
              v-model="nextStatus"
              class="rounded border border-slate-300 px-2 py-1.5 text-sm"
            >
              <option value="" disabled>Select a status</option>
              <option v-for="s in TRIP_STATUSES" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <div class="flex-1 space-y-1">
            <label class="text-sm font-medium text-slate-600" for="status_notes">Notes</label>
            <input
              id="status_notes"
              v-model="statusNotes"
              class="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            />
          </div>
          <button
            type="button"
            :disabled="!nextStatus || changingStatus"
            class="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            @click="onChangeStatus"
          >
            {{ changingStatus ? 'Updating…' : 'Apply' }}
          </button>
        </div>
      </section>

      <DeliveryControlForm
        v-if="trip.status === 'QUANTITY_CONTROL' && canChangeStatus"
        :trip-id="trip.id"
        :quantity-loaded="trip.quantity_loaded"
        @confirmed="load"
      />

      <section class="space-y-3 rounded border bg-white p-4">
        <h3 class="text-base font-semibold text-slate-800">History</h3>
        <ol class="space-y-3 border-l border-slate-200 pl-4">
          <li v-for="entry in history" :key="entry.id" class="relative text-sm">
            <span class="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-slate-400" />
            <p class="font-medium text-slate-800">
              {{ entry.previous_status }} → {{ entry.new_status }}
            </p>
            <p class="text-xs text-slate-500">
              {{ formatDateTime(entry.changed_at) }} · {{ entry.changed_by_detail?.email }}
            </p>
            <p v-if="entry.notes" class="text-slate-600">{{ entry.notes }}</p>
          </li>
          <li v-if="!history.length" class="text-slate-400">No status changes yet.</li>
        </ol>
      </section>
    </template>
  </div>
</template>
