<script setup lang="ts">
// docs/PHASE_4_PLAN.md Etape 9: quantity control / discharge form, embedded
// in TripDetail.vue while the trip sits at QUANTITY_CONTROL.
//
// The backend (DeliveryService.record_delivery(), guide §7.3/§15) is the
// sole authority on the loss/tolerance/anomaly rules and the final
// numbers - the live loss/chargeable-loss figures shown here while typing
// are an *estimate* only, using whichever tolerance this browser could
// read (falls back to the spec's 100 L default if the current user lacks
// "admin" view rights on /api/settings/loss-tolerance/). The authoritative,
// frozen values always come back in the POST response.
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { postDeliveryControl, type DeliveryControlPayload } from './api'
import { fetchLossTolerance } from '@/modules/settings/api'
import type { DeliveryControl, DeliveryMethod } from './types'

const props = defineProps<{
  tripId: number
  quantityLoaded: string
}>()
const emit = defineEmits<{
  confirmed: [control: DeliveryControl]
}>()

const auth = useAuthStore()

const DEFAULT_TOLERANCE_LITRES = 100

const toleranceLitres = ref(DEFAULT_TOLERANCE_LITRES)

onMounted(async () => {
  try {
    const config = await fetchLossTolerance()
    toleranceLitres.value = Number(config.tolerance_litres)
  } catch {
    // Not an admin (or the request otherwise failed) - keep the spec
    // default for the live estimate; the server freezes the real value.
  }
})

const form = ref({
  received_quantity: '',
  control_date: new Date().toISOString().slice(0, 10),
  method: 'MANUAL_GAUGE' as DeliveryMethod,
  notes: '',
})
const anomalyConfirmed = ref(false)

const loadedQty = computed(() => Number(props.quantityLoaded))
const receivedQty = computed(() => Number(form.value.received_quantity) || 0)
const hasReceivedInput = computed(() => form.value.received_quantity !== '')
const lossQty = computed(() => loadedQty.value - receivedQty.value)
const chargeableLossQty = computed(() => Math.max(lossQty.value - toleranceLitres.value, 0))
const isAnomaly = computed(() => hasReceivedInput.value && receivedQty.value > loadedQty.value)

// Anomaly confirmation is gated on the same "validate" tier the backend
// Role permission matrix already uses for other frozen/high-stakes actions
// (guide's "authorized user" - Admin by default, see accounts seed roles).
const canConfirmAnomaly = computed(() => auth.can('operations', 'validate'))

const canSubmit = computed(() => {
  if (!hasReceivedInput.value || !form.value.control_date) return false
  if (isAnomaly.value) return canConfirmAnomaly.value && anomalyConfirmed.value
  return true
})

const saving = ref(false)
const error = ref('')

async function onSubmit() {
  if (!canSubmit.value) return
  saving.value = true
  error.value = ''
  const payload: DeliveryControlPayload = {
    received_quantity: form.value.received_quantity,
    control_date: form.value.control_date,
    method: form.value.method,
    notes: form.value.notes,
  }
  if (isAnomaly.value && anomalyConfirmed.value && auth.user) {
    payload.anomaly_confirmed_by = auth.user.id
  }
  try {
    const control = await postDeliveryControl(props.tripId, payload)
    emit('confirmed', control)
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail || 'Could not record delivery.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="space-y-4 rounded border bg-white p-4" @submit.prevent="onSubmit">
    <h3 class="text-base font-semibold text-slate-800">Delivery / discharge control</h3>
    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <div class="grid grid-cols-2 gap-4">
      <div class="space-y-1">
        <span class="text-sm font-medium text-slate-600">Loaded quantity</span>
        <p id="loaded_quantity_display" class="text-sm font-medium text-slate-800">
          {{ loadedQty.toLocaleString() }} L
        </p>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="received_quantity"
          >Received quantity (L)</label
        >
        <input
          id="received_quantity"
          v-model="form.received_quantity"
          type="number"
          step="0.01"
          min="0"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="control_date">Control date</label>
        <input
          id="control_date"
          v-model="form.control_date"
          type="date"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="method">Method</label>
        <select
          id="method"
          v-model="form.method"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="MANUAL_GAUGE">Manual gauge</option>
          <option value="METER">Meter</option>
        </select>
      </div>
    </div>

    <div
      v-if="hasReceivedInput"
      class="grid grid-cols-2 gap-4 rounded border border-slate-200 bg-slate-50 p-3 text-sm"
    >
      <div>
        <span class="text-slate-500">Loss (est.)</span>
        <p class="font-medium text-slate-800">{{ lossQty.toLocaleString() }} L</p>
      </div>
      <div>
        <span class="text-slate-500">Chargeable loss (est.)</span>
        <p class="font-medium text-slate-800">{{ chargeableLossQty.toLocaleString() }} L</p>
      </div>
    </div>

    <div v-if="isAnomaly" class="space-y-2 rounded border border-amber-300 bg-amber-50 p-3">
      <p class="text-sm font-medium text-amber-800">
        Received quantity exceeds loaded quantity — this is an anomaly and requires authorized
        confirmation before it can be recorded.
      </p>
      <label v-if="canConfirmAnomaly" class="flex items-center gap-2 text-sm text-amber-900">
        <input id="anomaly_confirmed" v-model="anomalyConfirmed" type="checkbox" />
        I confirm this anomaly as an authorized user ({{ auth.user?.email }})
      </label>
      <p v-else class="text-sm text-amber-700">
        Ask an authorized user to confirm this anomaly before it can be recorded.
      </p>
    </div>

    <div class="space-y-1">
      <label class="text-sm font-medium text-slate-600" for="notes">Notes</label>
      <textarea
        id="notes"
        v-model="form.notes"
        rows="2"
        class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
      />
    </div>

    <div class="flex justify-end">
      <button
        type="submit"
        :disabled="!canSubmit || saving"
        class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {{ saving ? 'Recording…' : 'Confirm delivery' }}
      </button>
    </div>
  </form>
</template>
