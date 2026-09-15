<script setup lang="ts">
// Client modification Task 2: transporter fees per litre create payable
// debt. Opened from a trip's detail page (TripDetail.vue) to record a
// TransportPayment for calculation_method=PER_LITRE. The transporter is
// always the trip's own transporter - the backend rejects any other one
// (backend/apps/finance/serializers.py TransportPaymentSerializer.validate())
// - so it's shown read-only here rather than as a pickable dropdown.
// base_amount is never sent: the server derives it from
// trip.quantity_loaded * unit_price_per_litre.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { translateApiError } from '@/i18n/apiErrors'
import { transportPaymentResource } from './api'
import type { TransportPayment } from './types'
import Button from '@/components/ui/Button.vue'
import { formatMoney, formatQuantity, formatUnitMoney } from '@/utils/currency'

const props = defineProps<{
  tripId: number
  tripReference: string
  transporterId: number
  transporterName: string
  quantityLoaded: string
  title?: string
  payment?: TransportPayment | null
}>()
const emit = defineEmits<{ success: []; cancel: [] }>()
const { t } = useI18n()

const isPerLitre = computed(
  () => !props.payment || props.payment.calculation_method === 'PER_LITRE',
)
const unitPricePerLitre = ref(props.payment?.unit_price_per_litre ?? '')
const baseAmount = ref(props.payment?.base_amount ?? '')

const total = computed(() => {
  const quantity = Number(props.quantityLoaded)
  const price = Number(unitPricePerLitre.value)
  if (!quantity || !price) return null
  return quantity * price
})

const saving = ref(false)
const error = ref('')

async function onSubmit() {
  saving.value = true
  error.value = ''
  try {
    if (props.payment) {
      await transportPaymentResource.update(
        props.payment.id,
        isPerLitre.value
          ? {
              calculation_method: 'PER_LITRE',
              unit_price_per_litre: String(unitPricePerLitre.value),
            }
          : { base_amount: String(baseAmount.value) },
      )
    } else {
      await transportPaymentResource.create({
        trip: props.tripId,
        transporter: props.transporterId,
        calculation_method: 'PER_LITRE',
        // Vue 3.4+ auto-casts v-model on <input type="number"> to a JS
        // number - cast back to a string so the payload matches the
        // DecimalField-backed API contract exactly (never send a float).
        unit_price_per_litre: String(unitPricePerLitre.value),
      })
    }
    emit('success')
  } catch (e) {
    const data = (e as { response?: { data?: Record<string, string | string[]> } })?.response?.data
    const detail = data ? Object.values(data).flat().join(' ') : ''
    error.value = translateApiError(detail) || t('finance.transportPayment.saveError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <form
      class="border-ligne space-y-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <h2 class="font-display text-sm font-semibold uppercase">
        {{ title ?? t('finance.transportPayment.title') }}
      </h2>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.transportPayment.trip')
          }}</span>
          <p class="text-texte h-12 flex items-center">{{ tripReference }}</p>
        </div>

        <div class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.transportPayment.transporter')
          }}</span>
          <p class="text-texte h-12 flex items-center">{{ transporterName }}</p>
        </div>

        <div class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.transportPayment.quantityLoaded')
          }}</span>
          <p class="text-texte h-12 flex items-center">
            {{ formatQuantity(quantityLoaded) }}
          </p>
        </div>

        <div v-if="isPerLitre" class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="unit_price_per_litre">{{
            t('finance.transportPayment.unitPricePerLitre')
          }}</label>
          <input
            id="unit_price_per_litre"
            v-model="unitPricePerLitre"
            type="number"
            step="0.0001"
            min="0.0001"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div v-else class="space-y-1.5">
          <label for="commission_amount" class="text-texte-2 text-sm font-medium">{{
            t('finance.expensesView.table.amount')
          }}</label>
          <input
            id="commission_amount"
            v-model="baseAmount"
            type="number"
            min="0.01"
            step="0.01"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5"
          />
        </div>
      </div>

      <div
        v-if="isPerLitre"
        class="border-ligne flex items-center justify-between rounded-lg border bg-fond px-3.5 py-2.5 text-sm"
      >
        <span class="text-texte-2">
          {{ t('finance.transportPayment.calculation') }}
        </span>
        <span class="text-texte font-medium">
          {{ formatQuantity(quantityLoaded) }} × {{ formatUnitMoney(unitPricePerLitre || 0) }} =
          {{ total !== null ? formatMoney(total) : '—' }}
        </span>
      </div>

      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('cancel')">
          {{ t('common.cancel') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('finance.transportPayment.saving') : t('finance.transportPayment.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>
