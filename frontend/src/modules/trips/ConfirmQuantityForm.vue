<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// "Saisir la quantité reçue" for a trip attributed to a customer without a
// quantity (docs/superpowers/specs/2026-11-02-attribution-client-directe-
// design.md, section 3). Confirming delivers, creates the invoice from the
// received quantity and - for a walk-in - books the full cash payment on the
// chosen account. Used from Ventes and TripDetail.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { translateApiError } from '@/i18n/apiErrors'
import { confirmReceivedQuantity, type PaymentDestination } from './api'
import Button from '@/components/ui/Button.vue'
import PaymentAccountPicker from './PaymentAccountPicker.vue'
import LossEstimate from './LossEstimate.vue'
import { blockNonDigitInput } from '@/utils/numeric-input'
import { isWholeLitres, wholeLitres } from '@/utils/litres'

const props = defineProps<{ tripId: number; quantityLoaded: string; isWalkIn: boolean }>()
const emit = defineEmits<{ success: []; cancel: [] }>()
const { t } = useI18n()

const quantity = ref(wholeLitres(props.quantityLoaded))
const payment = ref<PaymentDestination | null>(null)
// The price was frozen at attribution; the backend re-checks it against the
// cost at invoicing time and answers 422 when it is now below cost.
const lossRequired = ref(false)
const lossConfirmed = ref(false)

const canSubmit = computed(() => {
  if (!isWholeLitres(quantity.value) || Number(quantity.value) > Number(props.quantityLoaded)) {
    return false
  }
  if (props.isWalkIn && !payment.value) return false
  if (lossRequired.value && !lossConfirmed.value) return false
  return true
})

const saving = ref(false)
const error = ref('')

async function onSubmit() {
  if (!canSubmit.value) return
  saving.value = true
  error.value = ''
  try {
    const payload: Parameters<typeof confirmReceivedQuantity>[1] = {
      received_quantity: String(quantity.value),
    }
    if (props.isWalkIn) payload.payment_destination = payment.value
    if (lossRequired.value) payload.confirm_loss = true
    await confirmReceivedQuantity(props.tripId, payload)
    emit('success')
  } catch (e) {
    const response = (e as { response?: { status?: number; data?: { detail?: string } } })?.response
    if (response?.status === 422) lossRequired.value = true
    error.value = translateApiError(response?.data?.detail) || t('trips.assignCustomer.quantityError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <AppAlert v-if="error" :message="error" />

    <form
      class="border-ligne space-y-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <h2 class="font-display text-sm font-semibold uppercase">
        {{ t('trips.assignCustomer.quantityTitle') }}
      </h2>
      <p class="text-texte-2 text-sm">{{ t('trips.assignCustomer.quantityHint') }}</p>

      <label class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{
          t('trips.assignCustomer.quantityTitle')
        }}</span>
        <input
          v-model="quantity"
          data-test="received-quantity"
          type="number"
          step="1"
          min="0"
          :max="wholeLitres(quantityLoaded)"
          @beforeinput="blockNonDigitInput"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </label>
      <LossEstimate :quantity-loaded="quantityLoaded" :received-quantity="quantity" />

      <div v-if="isWalkIn" class="space-y-2">
        <p class="text-sm font-semibold">{{ t('trips.assignCustomer.paymentTitle') }}</p>
        <p class="text-texte-3 text-xs">{{ t('trips.assignCustomer.paymentHint') }}</p>
        <PaymentAccountPicker v-model="payment" />
      </div>

      <div v-if="lossRequired" class="border-critique bg-critique-tint space-y-2 rounded-lg border p-3">
        <p class="text-critique-texte text-sm font-medium">{{ t('trips.delivery.lossWarning') }}</p>
        <label class="text-critique-texte flex items-center gap-2 text-sm">
          <input
            v-model="lossConfirmed"
            data-test="loss-confirm"
            type="checkbox"
            class="border-ligne-forte accent-orange h-5 w-5 rounded"
          />
          {{ t('trips.delivery.lossConfirm') }}
        </label>
      </div>

      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('cancel')">
          {{ t('common.cancel') }}
        </Button>
        <Button
          type="submit"
          variant="primary"
          data-test="submit"
          :disabled="!canSubmit"
          :loading="saving"
        >
          {{ saving ? t('trips.assignCustomer.saving') : t('trips.assignCustomer.quantitySave') }}
        </Button>
      </div>
    </form>
  </div>
</template>
