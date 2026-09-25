<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// Client modifications plan Task 9 (gap-closure): lets an operator earmark
// a COMPANY_STOCK trip for a customer once cost/logistics work is done -
// the core client workflow (spec section 3 / section 11 "Workflow global")
// of "create trip without client -> do the cost work -> then pick who it's
// sold to". Opened from TripDetail.vue's "Attribuer un client" action,
// only while destination_type is still COMPANY_STOCK and no Sale exists
// yet (TripDetail computes both - the backend re-validates the latter
// regardless via TripCostService.assign_customer_for_sale's
// CustomerAlreadySoldError).
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import { translateApiError } from '@/i18n/apiErrors'
import { assignTripCustomer, assignTripsCustomer } from './api'
import type { CustomerBrief } from './types'
import Button from '@/components/ui/Button.vue'
import SearchableSelect from '@/components/ui/SearchableSelect.vue'

// Single trip (tripId + tripReference) or several trips billed on one
// invoice (`trips`, from the Ventes "Attribuer un client" picker).
const props = defineProps<{
  tripId?: number
  tripReference?: string
  trips?: { id: number; reference: string }[]
}>()
const emit = defineEmits<{ success: []; cancel: [] }>()
const { t } = useI18n()

const customerResource = createResourceApi<CustomerBrief>('/customers/')
const customers = ref<CustomerBrief[]>([])
const customerId = ref('')

const customerOptions = computed(() =>
  customers.value.map((c) => ({ value: String(c.id), label: c.name })),
)

onMounted(async () => {
  const data = await customerResource.list()
  customers.value = data.results
})

const selectedTrips = computed(
  () =>
    props.trips ??
    (props.tripId !== undefined
      ? [{ id: props.tripId, reference: props.tripReference ?? '' }]
      : []),
)
const tripsLabel = computed(() => selectedTrips.value.map((trip) => trip.reference).join(', '))

const saving = ref(false)
const error = ref('')

async function onSubmit() {
  if (!customerId.value) return
  saving.value = true
  error.value = ''
  try {
    if (selectedTrips.value.length > 1) {
      await assignTripsCustomer(
        selectedTrips.value.map((trip) => trip.id),
        Number(customerId.value),
      )
    } else {
      await assignTripCustomer(selectedTrips.value[0].id, Number(customerId.value))
    }
    emit('success')
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = translateApiError(detail) || t('trips.assignCustomer.saveError')
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
        {{ t('trips.assignCustomer.title') }}
      </h2>

      <div class="space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{ t('trips.assignCustomer.trip') }}</span>
        <p class="text-texte flex min-h-12 items-center">{{ tripsLabel }}</p>
        <p v-if="selectedTrips.length > 1" class="text-texte-3 text-xs">
          {{ t('trips.assignCustomer.singleInvoiceHint') }}
        </p>
      </div>

      <label class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{
          t('trips.assignCustomer.customer')
        }}</span>
        <SearchableSelect
          v-model="customerId"
          :options="customerOptions"
          :placeholder="t('trips.assignCustomer.selectCustomer')"
        />
      </label>

      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('cancel')">
          {{ t('common.cancel') }}
        </Button>
        <Button type="submit" variant="primary" :disabled="!customerId" :loading="saving">
          {{ saving ? t('trips.assignCustomer.saving') : t('trips.assignCustomer.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>
