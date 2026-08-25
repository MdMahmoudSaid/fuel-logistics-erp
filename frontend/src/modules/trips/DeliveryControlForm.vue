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
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import {
  fetchSuggestedSellingPrice,
  postDeliveryControl,
  type DeliveryControlPayload,
} from './api'
import { translateApiError } from '@/i18n/apiErrors'
import { fetchLossTolerance } from '@/modules/settings/api'
import Button from '@/components/ui/Button.vue'
import type { DeliveryControl, DeliveryMethod } from './types'

const props = defineProps<{
  tripId: number
  quantityLoaded: string
}>()
const emit = defineEmits<{
  confirmed: [control: DeliveryControl]
}>()

const auth = useAuthStore()
const { t } = useI18n()

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
  unit_selling_price: '',
  notes: '',
})
const anomalyConfirmed = ref(false)

// Pre-fills from ProductSellingPriceHistory (backend/apps/sales/models.py)
// when one exists for this trip's product/customer, but is left editable -
// this is what unblocks confirmation when none does (Sale creation used to
// hard-fail with SellingPriceNotConfigured, see DeliveryService.record_delivery()).
onMounted(async () => {
  try {
    form.value.unit_selling_price = (await fetchSuggestedSellingPrice(props.tripId)) ?? ''
  } catch {
    // No suggestion available - the field just starts empty for manual entry.
  }
})

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
  if (!hasReceivedInput.value || !form.value.control_date || !form.value.unit_selling_price)
    return false
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
    unit_selling_price: form.value.unit_selling_price,
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
    error.value = translateApiError(detail) || t('trips.delivery.recordError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="border-ligne space-y-4 rounded-xl border bg-surface p-6" @submit.prevent="onSubmit">
    <h2 class="font-display text-lg leading-none font-semibold uppercase">
      {{ t('trips.delivery.title') }}
    </h2>
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <div class="grid grid-cols-2 gap-4">
      <div class="space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{ t('trips.delivery.loadedQuantity') }}</span>
        <p id="loaded_quantity_display" class="text-texte text-sm font-medium">
          {{ loadedQty.toLocaleString() }} L
        </p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="received_quantity">{{
          t('trips.delivery.receivedQuantity')
        }}</label>
        <input
          id="received_quantity"
          v-model="form.received_quantity"
          type="number"
          step="0.01"
          min="0"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="control_date">{{
          t('trips.delivery.controlDate')
        }}</label>
        <input
          id="control_date"
          v-model="form.control_date"
          type="date"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="method">{{
          t('trips.delivery.method')
        }}</label>
        <select
          id="method"
          v-model="form.method"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option value="MANUAL_GAUGE">{{ t('trips.delivery.manualGauge') }}</option>
          <option value="METER">{{ t('trips.delivery.meter') }}</option>
        </select>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="unit_selling_price">{{
          t('trips.delivery.unitSellingPrice')
        }}</label>
        <input
          id="unit_selling_price"
          v-model="form.unit_selling_price"
          type="number"
          step="0.0001"
          min="0"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>
    </div>

    <div
      v-if="hasReceivedInput"
      class="border-ligne grid grid-cols-2 gap-4 rounded-lg border bg-sable p-3 text-sm"
    >
      <div>
        <span class="text-texte-2">{{ t('trips.delivery.lossEstimate') }}</span>
        <p class="text-texte font-medium">{{ lossQty.toLocaleString() }} L</p>
      </div>
      <div>
        <span class="text-texte-2">{{ t('trips.delivery.chargeableLossEstimate') }}</span>
        <p class="text-texte font-medium">{{ chargeableLossQty.toLocaleString() }} L</p>
      </div>
    </div>

    <div v-if="isAnomaly" class="border-ecart bg-ecart-tint space-y-2 rounded-lg border p-3">
      <p class="text-ecart-texte text-sm font-medium">
        {{ t('trips.delivery.anomalyWarning') }}
      </p>
      <label v-if="canConfirmAnomaly" class="text-ecart-texte flex items-center gap-2 text-sm">
        <input
          id="anomaly_confirmed"
          v-model="anomalyConfirmed"
          type="checkbox"
          class="border-ligne-forte accent-orange h-5 w-5 rounded"
        />
        {{ t('trips.delivery.anomalyConfirm', { email: auth.user?.email ?? '' }) }}
      </label>
      <p v-else class="text-ecart-texte text-sm">
        {{ t('trips.delivery.anomalyAskAuthorized') }}
      </p>
    </div>

    <div class="space-y-1.5">
      <label class="text-texte-2 text-sm font-medium" for="notes">{{
        t('trips.detail.notes')
      }}</label>
      <textarea
        id="notes"
        v-model="form.notes"
        rows="2"
        class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      />
    </div>

    <div class="flex justify-end">
      <Button type="submit" variant="primary" :disabled="!canSubmit" :loading="saving">
        {{ saving ? t('trips.delivery.recording') : t('trips.delivery.confirmDelivery') }}
      </Button>
    </div>
  </form>
</template>
