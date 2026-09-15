<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// Feedback (2026-09-10): the "Declarer une perte" button's wording led
// operators to type the loss instead of the received quantity, with no way
// to fix the mistake - DeliveryService.correct_client_verification() is the
// audited fix path (previous/new value + reason + actor, same shape as
// InvoiceDetail.vue's correction form). Only shown once a first
// verification already exists (see canShowVerificationCorrection in
// TripDetail.vue).
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { postClientVerificationCorrection } from './api'
import { translateApiError } from '@/i18n/apiErrors'
import Button from '@/components/ui/Button.vue'
import type { DeliveryControl } from './types'
import { formatQuantity } from '@/utils/currency'

const props = defineProps<{
  tripId: number
  currentReceivedQuantity: string
}>()
const emit = defineEmits<{
  corrected: [control: DeliveryControl]
  cancel: []
}>()

const { t } = useI18n()

const form = ref({
  received_quantity: '',
  reason: '',
})

const canSubmit = () => form.value.received_quantity !== '' && form.value.reason.trim() !== ''

const saving = ref(false)
const error = ref('')

async function onSubmit() {
  if (!canSubmit()) return
  saving.value = true
  error.value = ''
  try {
    const control = await postClientVerificationCorrection(props.tripId, {
      received_quantity: form.value.received_quantity,
      reason: form.value.reason,
    })
    emit('corrected', control)
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = translateApiError(detail) || t('trips.clientVerificationCorrection.recordError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="border-ligne space-y-4 rounded-xl border bg-surface p-6" @submit.prevent="onSubmit">
    <h2 class="font-display text-lg leading-none font-semibold uppercase">
      {{ t('trips.clientVerificationCorrection.title') }}
    </h2>
    <p class="text-texte-2 text-sm">
      {{ t('trips.clientVerificationCorrection.hint') }}
    </p>
    <AppAlert v-if="error" :message="error" />

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{
          t('trips.clientVerificationCorrection.currentReceivedQuantity')
        }}</span>
        <p class="text-texte text-sm font-medium">
          {{ formatQuantity(currentReceivedQuantity) }}
        </p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="correction_received_quantity">{{
          t('trips.clientVerificationCorrection.newReceivedQuantity')
        }}</label>
        <input
          id="correction_received_quantity"
          v-model="form.received_quantity"
          data-test="correction-received-quantity"
          type="number"
          step="0.01"
          min="0"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>
    </div>

    <div class="space-y-1.5">
      <label class="text-texte-2 text-sm font-medium" for="correction_reason">{{
        t('trips.clientVerificationCorrection.reason')
      }}</label>
      <textarea
        id="correction_reason"
        v-model="form.reason"
        data-test="correction-reason"
        required
        rows="2"
        class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      />
    </div>

    <div class="flex justify-end gap-2">
      <Button type="button" variant="ghost" @click="emit('cancel')">
        {{ t('common.cancel') }}
      </Button>
      <Button type="submit" variant="primary" :disabled="!canSubmit() || saving" :loading="saving">
        {{
          saving
            ? t('trips.clientVerificationCorrection.recording')
            : t('trips.clientVerificationCorrection.submit')
        }}
      </Button>
    </div>
  </form>
</template>
