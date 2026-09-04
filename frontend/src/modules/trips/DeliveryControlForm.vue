<script setup lang="ts">
// docs/PHASE_4_PLAN.md Etape 9: delivery confirmation form, embedded in
// TripDetail.vue from ARRIVED_AT_CLIENT (and, for backward-compat, legacy
// trips still sitting at QUANTITY_CONTROL).
//
// Client modifications (2026-09-04 recette corrections): the delivery flow
// was simplified - `received_quantity` is no longer collected here at all.
// The backend (DeliveryService.record_delivery()) always defaults it to the
// full loaded quantity (zero loss) when it's omitted from the payload, so
// the trip goes straight to DELIVERED. Any discrepancy the client reports
// afterwards is handled post-delivery by ClientVerificationForm.vue via the
// separate client-verification endpoint - this form no longer shows a
// loss/anomaly estimate at all. The below-cost "vente à perte" gate is a
// different concept (selling price vs. cost price) and is unaffected.
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  fetchSuggestedSellingPrice,
  fetchTripCostBasis,
  postDeliveryControl,
  type DeliveryControlPayload,
} from './api'
import { translateApiError } from '@/i18n/apiErrors'
import Button from '@/components/ui/Button.vue'
import type { DeliveryControl, DeliveryMethod, TripCostBasis } from './types'
import { formatQuantity, formatUnitMoney } from '@/utils/currency'

const props = defineProps<{
  tripId: number
  quantityLoaded: string
}>()
const emit = defineEmits<{
  confirmed: [control: DeliveryControl]
}>()

const { t } = useI18n()

const form = ref({
  control_date: new Date().toISOString().slice(0, 10),
  method: 'MANUAL_GAUGE' as DeliveryMethod,
  unit_selling_price: '',
  notes: '',
})

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

// Client modifications Task 3: "prix de revient" (TripCostService.
// calculate_trip_cost_basis, available from the moment a trip is loaded)
// used to show the live per-litre benefit as the operator edits the
// selling price above, and to gate the loss-confirmation checkbox below.
const costBasis = ref<TripCostBasis | null>(null)
onMounted(async () => {
  try {
    costBasis.value = await fetchTripCostBasis(props.tripId)
  } catch {
    // Cost basis unavailable - the price-de-revient/benefit hints just
    // stay hidden; the backend still enforces the below-cost guard.
  }
})

const lossConfirmed = ref(false)

const loadedQty = computed(() => Number(props.quantityLoaded))

const unitCost = computed(() => (costBasis.value ? Number(costBasis.value.unit_cost) : null))
const hasSellingPriceInput = computed(() => form.value.unit_selling_price !== '')
const benefit = computed(() =>
  unitCost.value !== null && hasSellingPriceInput.value
    ? Number(form.value.unit_selling_price) - unitCost.value
    : null,
)
const isLoss = computed(() => benefit.value !== null && benefit.value < 0)
const isBreakEven = computed(() => benefit.value === 0)
const resultText = computed(() => {
  if (benefit.value === null) return ''
  const amount = formatUnitMoney(Math.abs(benefit.value))
  if (benefit.value > 0) return t('trips.delivery.profitResult', { amount })
  if (benefit.value < 0) return t('trips.delivery.lossResult', { amount })
  return t('trips.delivery.breakEvenResult')
})
const componentRows = computed(() => {
  if (!costBasis.value) return []
  const components = costBasis.value.unit_components_per_litre
  return [
    { label: t('trips.delivery.supplierPrice'), value: Number(components.supplier) },
    {
      label: t('trips.delivery.transporterCommission'),
      value: Number(components.commission_transporter),
    },
    { label: t('trips.delivery.roadTransit'), value: Number(components.road_transit) },
    { label: t('trips.delivery.transit'), value: Number(components.transit) },
    { label: t('trips.delivery.border'), value: Number(components.border) },
    { label: t('trips.delivery.customs'), value: Number(components.customs) },
    { label: t('trips.delivery.loading'), value: Number(components.loading) },
    { label: t('trips.delivery.otherFees'), value: Number(components.other) },
  ]
})

const canSubmit = computed(() => {
  if (!form.value.control_date || !form.value.unit_selling_price) return false
  if (isLoss.value && !lossConfirmed.value) return false
  return true
})

const saving = ref(false)
const error = ref('')

async function onSubmit() {
  if (!canSubmit.value) return
  saving.value = true
  error.value = ''
  const payload: DeliveryControlPayload = {
    control_date: form.value.control_date,
    method: form.value.method,
    unit_selling_price: form.value.unit_selling_price,
    notes: form.value.notes,
  }
  if (isLoss.value && lossConfirmed.value) {
    payload.confirm_loss = true
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

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{
          t('trips.delivery.loadedQuantity')
        }}</span>
        <p id="loaded_quantity_display" class="text-texte text-sm font-medium">
          {{ formatQuantity(loadedQty) }}
        </p>
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
      v-if="unitCost !== null"
      class="border-ligne space-y-3 rounded-lg border bg-sable p-3 text-sm"
    >
      <dl class="divide-ligne divide-y">
        <div
          v-for="row in componentRows"
          :key="row.label"
          class="flex items-center justify-between py-1.5"
        >
          <dt class="text-texte-2">{{ row.label }}</dt>
          <dd class="text-texte font-medium">{{ formatUnitMoney(row.value) }}</dd>
        </div>
        <div class="flex items-center justify-between py-1.5">
          <dt class="text-texte font-semibold">{{ t('trips.delivery.costBasis') }}</dt>
          <dd class="text-texte font-semibold">{{ formatUnitMoney(unitCost) }}</dd>
        </div>
        <div v-if="hasSellingPriceInput" class="flex items-center justify-between py-1.5">
          <dt class="text-texte-2">{{ t('trips.delivery.enteredSellingPrice') }}</dt>
          <dd class="text-texte font-medium">
            {{ formatUnitMoney(form.unit_selling_price) }}
          </dd>
        </div>
        <div v-if="benefit !== null" class="flex items-center justify-between py-1.5">
          <dt class="text-texte-2">{{ t('trips.delivery.result') }}</dt>
          <dd
            class="font-medium"
            :class="isLoss ? 'text-critique' : isBreakEven ? 'text-texte' : 'text-livre'"
          >
            {{ resultText }}
          </dd>
        </div>
      </dl>
    </div>

    <div v-if="isLoss" class="border-critique bg-critique-tint space-y-2 rounded-lg border p-3">
      <p class="text-critique-texte text-xs font-semibold uppercase">
        {{ t('trips.delivery.lossTitle') }}
      </p>
      <p class="text-critique-texte text-sm font-medium">
        {{ t('trips.delivery.lossWarning') }}
      </p>
      <label class="text-critique-texte flex items-center gap-2 text-sm">
        <input
          id="loss_confirmed"
          v-model="lossConfirmed"
          type="checkbox"
          class="border-ligne-forte accent-orange h-5 w-5 rounded"
        />
        {{ t('trips.delivery.lossConfirm') }}
      </label>
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
