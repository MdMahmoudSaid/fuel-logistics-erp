<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// Client modifications (2026-09-04 recette corrections): post-delivery
// client verification. Once a trip is DELIVERED/COMPLETED, the client may
// report that the quantity actually received differs from what was
// confirmed at delivery time (DeliveryControlForm.vue, which - per the
// simplified flow - always defaults to zero loss). This form records that
// check via POST /api/trips/{id}/client-verification/
// (DeliveryService.record_client_verification()), which is the sole
// authority on the final loss/tolerance split. The company-absorbed vs.
// transporter-chargeable figures shown here while typing are an *estimate*
// only, using whichever tolerance this browser could read (falls back to
// the spec's 100 L default) - same convention as DeliveryControlForm.vue.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { postClientVerification, type ClientVerificationPayload } from './api'
import { translateApiError } from '@/i18n/apiErrors'
import LossEstimate from './LossEstimate.vue'
import { blockNonDigitInput } from '@/utils/numeric-input'
import Button from '@/components/ui/Button.vue'
import type { DeliveryControl } from './types'
import { formatQuantity } from '@/utils/currency'

const props = defineProps<{
  tripId: number
  quantityLoaded: string
}>()
const emit = defineEmits<{
  verified: [control: DeliveryControl]
}>()

const { t } = useI18n()

const form = ref({
  received_quantity: '',
  verified_at: new Date().toISOString().slice(0, 10),
  notes: '',
})

const loadedQty = computed(() => Number(props.quantityLoaded))
const hasReceivedInput = computed(() => form.value.received_quantity !== '')

const canSubmit = computed(() => hasReceivedInput.value && !!form.value.verified_at)

const saving = ref(false)
const error = ref('')

async function onSubmit() {
  if (!canSubmit.value) return
  saving.value = true
  error.value = ''
  const payload: ClientVerificationPayload = {
    received_quantity: form.value.received_quantity,
    verified_at: form.value.verified_at,
    notes: form.value.notes,
  }
  try {
    const control = await postClientVerification(props.tripId, payload)
    emit('verified', control)
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = translateApiError(detail) || t('trips.clientVerification.recordError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="border-ligne space-y-4 rounded-xl border bg-surface p-6" @submit.prevent="onSubmit">
    <h2 class="font-display text-lg leading-none font-semibold uppercase">
      {{ t('trips.clientVerification.title') }}
    </h2>
    <AppAlert v-if="error" :message="error" />

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{
          t('trips.clientVerification.loadedQuantity')
        }}</span>
        <p id="loaded_quantity_display" class="text-texte text-sm font-medium">
          {{ formatQuantity(loadedQty) }}
        </p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="received_quantity">{{
          t('trips.clientVerification.receivedQuantity')
        }}</label>
        <input
          id="received_quantity"
          v-model="form.received_quantity"
          data-test="received-quantity"
          type="number"
          step="1"
          min="0"
          required
          @beforeinput="blockNonDigitInput"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p class="text-texte-3 text-xs">{{ t('trips.clientVerification.receivedQuantityHint') }}</p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="verified_at">{{
          t('trips.clientVerification.verifiedAt')
        }}</label>
        <input
          id="verified_at"
          v-model="form.verified_at"
          type="date"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>
    </div>

    <LossEstimate :quantity-loaded="quantityLoaded" :received-quantity="form.received_quantity" />

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
        {{
          saving ? t('trips.clientVerification.recording') : t('trips.clientVerification.submit')
        }}
      </Button>
    </div>
  </form>
</template>
