<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { tripResource, fetchTripHistory, postTripStatus } from './api'
import { translateApiError } from '@/i18n/apiErrors'
import DeliveryControlForm from './DeliveryControlForm.vue'
import { TRIP_STATUSES } from './types'
import type { Trip, TripStatus, TripStatusHistoryEntry } from './types'
import { fetchReport } from '@/modules/reports/api'
import { lossSeverityTone, type LossReportRow } from '@/modules/dashboard/aggregate'
import GaugeBar from '@/components/ui/GaugeBar.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { useTripStatusLabel } from './tripStatusLabels'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()
const statusLabel = useTripStatusLabel()

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
    error.value = t('trips.detail.loadError')
  } finally {
    loading.value = false
  }
}

onMounted(load)

// docs/UI_REDESIGN_PLAN.md Etape 6.2: bloc "Jauges" (chargé/livré/écart).
// Pas de champ dédié sur Trip pour la quantité livrée - le DeliveryControl
// associé n'est pas non plus imbriqué dans TripSerializer (backend/apps/
// trips/serializers.py), et il n'existe aucun endpoint de lecture pour un
// DeliveryControl isolé (seule sa création via POST /trips/{id}/delivery-
// control/ est exposée). Le loss-report existant expose déjà ces champs par
// trip_reference - on le réutilise plutôt que d'ajouter un endpoint backend
// pour ce seul affichage.
const deliveryData = ref<LossReportRow | null>(null)

watch(
  () => trip.value?.status,
  async (status) => {
    if (status !== 'DELIVERED' && status !== 'COMPLETED') {
      deliveryData.value = null
      return
    }
    try {
      const report = await fetchReport('loss-report', {})
      const rows = report.rows as unknown as LossReportRow[]
      deliveryData.value = rows.find((row) => row.trip_reference === trip.value?.reference) ?? null
    } catch {
      deliveryData.value = null
    }
  },
)

const deliveredPct = computed(() => {
  if (!deliveryData.value) return 0
  const loaded = Number(deliveryData.value.loaded_quantity)
  return loaded > 0 ? (Number(deliveryData.value.received_quantity) / loaded) * 100 : 0
})
const lossPct = computed(() => {
  if (!deliveryData.value) return 0
  const loaded = Number(deliveryData.value.loaded_quantity)
  return loaded > 0 ? (Number(deliveryData.value.loss_quantity) / loaded) * 100 : 0
})

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
    statusError.value = translateApiError(data?.detail) || t('trips.detail.statusChangeError')
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
      <h2 class="text-lg font-semibold text-slate-800">
        {{ t('trips.detail.title', { reference: trip?.reference ?? '' }) }}
      </h2>
      <button class="px-3 py-2 text-sm text-slate-500" @click="router.push({ name: 'trips' })">
        {{ t('trips.detail.backToBoard') }}
      </button>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">{{ t('common.loading') }}</p>

    <template v-else-if="trip">
      <section class="grid grid-cols-2 gap-4 rounded border bg-white p-4 text-sm">
        <div>
          <span class="text-slate-500">{{ t('trips.detail.status') }}</span>
          <p>
            <span
              class="rounded-full px-2 py-0.5 text-xs font-medium"
              :class="STATUS_BADGE[trip.status] ?? 'bg-amber-100 text-amber-700'"
            >
              {{ statusLabel(trip.status) }}
            </span>
          </p>
        </div>
        <div>
          <span class="text-slate-500">{{ t('trips.detail.truck') }}</span>
          <p class="font-medium text-slate-800">{{ trip.truck_detail?.internal_id }}</p>
        </div>
        <div>
          <span class="text-slate-500">{{ t('trips.detail.transporter') }}</span>
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
          <span class="text-slate-500">{{ t('trips.detail.driver') }}</span>
          <p class="font-medium text-slate-800">{{ trip.driver_detail?.name ?? '—' }}</p>
        </div>
        <div>
          <span class="text-slate-500">{{ t('trips.detail.supplier') }}</span>
          <p class="font-medium text-slate-800">{{ trip.supplier_detail?.name }}</p>
        </div>
        <div>
          <span class="text-slate-500">{{ t('trips.detail.product') }}</span>
          <p class="font-medium text-slate-800">{{ trip.product_detail?.name }}</p>
        </div>
        <div>
          <span class="text-slate-500">{{ t('trips.detail.quantityLoaded') }}</span>
          <p class="font-medium text-slate-800">
            {{ Number(trip.quantity_loaded).toLocaleString() }} L
          </p>
        </div>
        <div>
          <span class="text-slate-500">{{ t('trips.detail.loadingDate') }}</span>
          <p class="font-medium text-slate-800">{{ trip.loading_date }}</p>
        </div>
        <div>
          <span class="text-slate-500">{{ t('trips.detail.blReference') }}</span>
          <p class="font-medium text-slate-800">{{ trip.bl_reference }}</p>
        </div>
        <div>
          <span class="text-slate-500">{{ t('trips.detail.client') }}</span>
          <p class="font-medium text-slate-800">
            {{ trip.client_detail?.name ?? (trip.customer_order ? '—' : t('trips.directSale')) }}
          </p>
        </div>
        <div v-if="trip.customer_order">
          <span class="text-slate-500">{{ t('trips.detail.customerOrder') }}</span>
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
          <span class="text-slate-500">{{ t('trips.detail.notes') }}</span>
          <p class="font-medium text-slate-800">{{ trip.notes }}</p>
        </div>
      </section>

      <section v-if="canChangeStatus" class="space-y-3 rounded border bg-white p-4">
        <h3 class="text-base font-semibold text-slate-800">{{ t('trips.detail.changeStatus') }}</h3>
        <p v-if="statusError" class="text-sm text-red-600">{{ statusError }}</p>

        <div class="flex flex-wrap items-end gap-2">
          <div class="space-y-1">
            <label class="text-sm font-medium text-slate-600" for="next_status">{{
              t('trips.detail.nextStatus')
            }}</label>
            <select
              id="next_status"
              v-model="nextStatus"
              class="rounded border border-slate-300 px-2 py-1.5 text-sm"
            >
              <option value="" disabled>{{ t('trips.detail.selectStatus') }}</option>
              <option v-for="s in TRIP_STATUSES" :key="s" :value="s">{{ statusLabel(s) }}</option>
            </select>
          </div>
          <div class="flex-1 space-y-1">
            <label class="text-sm font-medium text-slate-600" for="status_notes">{{
              t('trips.detail.notes')
            }}</label>
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
            {{ changingStatus ? t('trips.detail.updating') : t('trips.detail.apply') }}
          </button>
        </div>
      </section>

      <DeliveryControlForm
        v-if="trip.status === 'QUANTITY_CONTROL' && canChangeStatus"
        :trip-id="trip.id"
        :quantity-loaded="trip.quantity_loaded"
        @confirmed="load"
      />

      <section v-if="deliveryData" class="border-ligne space-y-4 rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 text-sm font-semibold uppercase">{{ t('trips.detail.gauges') }}</h3>
        <div class="grid grid-cols-3 gap-4">
          <div>
            <p class="text-texte-3 text-xs uppercase">{{ t('trips.detail.loaded') }}</p>
            <MonoValue
              :value="Number(deliveryData.loaded_quantity).toLocaleString()"
              unit="L"
              align="left"
            />
          </div>
          <div>
            <p class="text-texte-3 text-xs uppercase">{{ t('trips.detail.delivered') }}</p>
            <MonoValue
              :value="Number(deliveryData.received_quantity).toLocaleString()"
              unit="L"
              align="left"
            />
          </div>
          <div>
            <p class="text-texte-3 text-xs uppercase">{{ t('trips.detail.gap') }}</p>
            <MonoValue
              :value="Number(deliveryData.loss_quantity).toLocaleString()"
              unit="L"
              align="left"
              :class="Number(deliveryData.chargeable_loss_quantity) > 0 ? 'text-critique' : ''"
            />
          </div>
        </div>
        <GaugeBar :value="deliveredPct" tone="livre" :label="t('trips.detail.deliveredOverLoaded')" />
        <GaugeBar
          :value="Math.min(100, (lossPct / 5) * 100)"
          :tone="lossSeverityTone(lossPct)"
          :label="t('trips.detail.gap')"
        />
      </section>

      <section class="space-y-3 rounded border bg-white p-4">
        <h3 class="text-base font-semibold text-slate-800">{{ t('trips.detail.history') }}</h3>
        <ol class="space-y-3 border-l border-slate-200 pl-4">
          <li v-for="entry in history" :key="entry.id" class="relative text-sm">
            <span class="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-slate-400" />
            <p class="font-medium text-slate-800">
              {{ statusLabel(entry.previous_status as TripStatus) }} →
              {{ statusLabel(entry.new_status as TripStatus) }}
            </p>
            <p class="text-xs text-slate-500">
              {{ formatDateTime(entry.changed_at) }} · {{ entry.changed_by_detail?.email }}
            </p>
            <p v-if="entry.notes" class="text-slate-600">{{ entry.notes }}</p>
          </li>
          <li v-if="!history.length" class="text-slate-400">{{ t('trips.detail.noHistory') }}</li>
        </ol>
      </section>
    </template>
  </div>
</template>
