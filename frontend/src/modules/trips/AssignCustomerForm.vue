<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// Direct sale (docs/superpowers/specs/2026-11-02-attribution-client-directe-
// design.md): opened from Ventes ("Attribuer un client", one or several
// picked trips) and from TripDetail (one trip). Picks a registered customer
// or a walk-in ("client de passage": name only, pays everything in cash),
// shows the cost price (single line, eye = full breakdown), takes the selling
// price with a live profit/loss, and optionally the received quantity. One
// POST (/trips/direct-sale/) links, arrives, parks the price and - when the
// quantity is given - delivers and invoices (walk-in: plus the cash payment).
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import { translateApiError } from '@/i18n/apiErrors'
import { fetchTripCostBasis, postDirectSale, type PaymentDestination } from './api'
import type { CustomerBrief, TripCostBasis } from './types'
import Button from '@/components/ui/Button.vue'
import SearchableSelect from '@/components/ui/SearchableSelect.vue'
import PaymentAccountPicker from './PaymentAccountPicker.vue'
import LossEstimate from './LossEstimate.vue'
import { blockNonDigitInput } from '@/utils/numeric-input'
import { isWholeLitres, wholeLitres } from '@/utils/litres'
import { formatUnitMoney } from '@/utils/currency'

// Single trip (tripId + tripReference) or several trips billed on one
// invoice (`trips`, from the Ventes picker).
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
const walkInName = ref('')

const customerOptions = computed(() =>
  customers.value.map((c) => ({ value: String(c.id), label: c.name })),
)
// "Client de passage" is a mode of the sale, not a customer: a toggle above
// the customer field, so it is never mistaken for a registered customer's name.
const mode = ref<'registered' | 'walk_in'>('registered')
const isWalkIn = computed(() => mode.value === 'walk_in')

const selectedTrips = computed(
  () =>
    props.trips ??
    (props.tripId !== undefined
      ? [{ id: props.tripId, reference: props.tripReference ?? '' }]
      : []),
)
const tripsLabel = computed(() => selectedTrips.value.map((trip) => trip.reference).join(', '))

const costBases = ref<Record<number, TripCostBasis>>({})
onMounted(async () => {
  const data = await customerResource.list()
  customers.value = data.results
  await Promise.all(
    selectedTrips.value.map(async (trip) => {
      try {
        costBases.value[trip.id] = await fetchTripCostBasis(trip.id)
      } catch {
        // Cost unavailable: the hints stay hidden, the backend still guards below-cost sales.
      }
    }),
  )
})

// Quantity-weighted per-litre cost across the picked trips (one trip = its own).
function weighted(pick: (basis: TripCostBasis) => string): number | null {
  const bases = selectedTrips.value.map((trip) => costBases.value[trip.id]).filter(Boolean)
  if (bases.length !== selectedTrips.value.length || bases.length === 0) return null
  const litres = bases.reduce((sum, b) => sum + Number(b.quantity), 0)
  if (litres === 0) return null
  return bases.reduce((sum, b) => sum + Number(pick(b)) * Number(b.quantity), 0) / litres
}
const customerChosen = computed(() => isWalkIn.value || customerId.value !== '')
const unitCost = computed(() => weighted((b) => b.unit_cost))
const showCostDetails = ref(false)
const componentRows = computed(() => {
  const rows: [string, (b: TripCostBasis) => string][] = [
    ['supplierPrice', (b) => b.unit_components_per_litre.supplier],
    ['transporterCommission', (b) => b.unit_components_per_litre.commission_transporter],
    ['loading', (b) => b.unit_components_per_litre.loading],
    ['roadTransit', (b) => b.unit_components_per_litre.road_transit],
    ['transit', (b) => b.unit_components_per_litre.transit],
    ['border', (b) => b.unit_components_per_litre.border],
    ['customs', (b) => b.unit_components_per_litre.customs],
    ['otherFees', (b) => b.unit_components_per_litre.other],
  ]
  return rows.map(([key, pick]) => ({
    label: t(`trips.delivery.${key}`),
    value: weighted(pick) ?? 0,
  }))
})

const unitPrice = ref('')
const hasPrice = computed(() => unitPrice.value !== '' && Number(unitPrice.value) > 0)
const benefit = computed(() =>
  unitCost.value !== null && hasPrice.value ? Number(unitPrice.value) - unitCost.value : null,
)
// The backend checks every trip against its own cost, so a loss on ANY trip
// needs the confirmation, whatever the weighted average says. `lossRequired`
// covers the case the client cannot see (cost unavailable): the backend's 422.
const belowCostOnATrip = computed(
  () =>
    hasPrice.value &&
    selectedTrips.value.some((trip) => {
      const basis = costBases.value[trip.id]
      return basis !== undefined && Number(unitPrice.value) < Number(basis.unit_cost)
    }),
)
const lossRequired = ref(false)
const isLoss = computed(
  () => (benefit.value !== null && benefit.value < 0) || belowCostOnATrip.value || lossRequired.value,
)
const lossConfirmed = ref(false)
const resultText = computed(() => {
  if (benefit.value === null) return ''
  const amount = formatUnitMoney(Math.abs(benefit.value))
  if (benefit.value > 0) return t('trips.delivery.profitResult', { amount })
  if (benefit.value < 0) return t('trips.delivery.lossResult', { amount })
  return t('trips.delivery.breakEvenResult')
})

const quantityNow = ref(false)
const quantities = ref<Record<number, string>>({})
function quantityFor(tripId: number): string {
  return quantities.value[tripId] ?? wholeLitres(costBases.value[tripId]?.quantity)
}
const payment = ref<PaymentDestination | null>(null)

const canSubmit = computed(() => {
  if (!customerChosen.value || !hasPrice.value) return false
  if (isWalkIn.value && !walkInName.value.trim()) return false
  if (isLoss.value && !lossConfirmed.value) return false
  if (quantityNow.value) {
    if (selectedTrips.value.some((trip) => !isWholeLitres(quantityFor(trip.id)))) return false
    if (isWalkIn.value && !payment.value) return false
  }
  return true
})

const saving = ref(false)
const error = ref('')

async function onSubmit() {
  if (!canSubmit.value) return
  saving.value = true
  error.value = ''
  try {
    const payload: Parameters<typeof postDirectSale>[0] = {
      trips: selectedTrips.value.map((trip) => trip.id),
      unit_selling_price: String(unitPrice.value),
    }
    if (isWalkIn.value) payload.walk_in_name = walkInName.value.trim()
    else payload.customer = Number(customerId.value)
    if (quantityNow.value) {
      payload.received_quantities = Object.fromEntries(
        selectedTrips.value.map((trip) => [String(trip.id), quantityFor(trip.id)]),
      )
      if (isWalkIn.value) payload.payment_destination = payment.value
    }
    if (isLoss.value) payload.confirm_loss = true
    await postDirectSale(payload)
    emit('success')
  } catch (e) {
    const response = (e as { response?: { status?: number; data?: { detail?: string } } })?.response
    if (response?.status === 422) lossRequired.value = true
    error.value = translateApiError(response?.data?.detail) || t('trips.assignCustomer.saveError')
  } finally {
    saving.value = false
  }
}

const inputClass =
  'border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'
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

      <div
        class="bg-sable grid grid-cols-2 gap-1 rounded-lg p-1"
        role="group"
        :aria-label="t('trips.assignCustomer.customer')"
      >
        <button
          v-for="option in [
            { key: 'registered', label: t('trips.assignCustomer.registeredCustomer') },
            { key: 'walk_in', label: t('trips.assignCustomer.walkIn') },
          ] as const"
          :key="option.key"
          type="button"
          :data-test="`mode-${option.key === 'walk_in' ? 'walk-in' : 'registered'}`"
          :aria-pressed="mode === option.key"
          class="h-10 rounded-md text-sm font-medium transition"
          :class="
            mode === option.key
              ? 'bg-white text-texte shadow-sm'
              : 'text-texte-2 hover:text-texte'
          "
          @click="mode = option.key"
        >
          {{ option.label }}
        </button>
      </div>

      <label v-if="!isWalkIn" class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{
          t('trips.assignCustomer.customer')
        }}</span>
        <SearchableSelect
          v-model="customerId"
          :options="customerOptions"
          :placeholder="t('trips.assignCustomer.selectCustomer')"
        />
      </label>

      <div v-if="isWalkIn" class="space-y-1.5">
        <label class="block space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('trips.assignCustomer.walkInName')
          }}</span>
          <input v-model="walkInName" data-test="walk-in-name" type="text" :class="inputClass" />
        </label>
        <p class="text-texte-3 text-xs">{{ t('trips.assignCustomer.walkInHint') }}</p>
      </div>

      <template v-if="customerChosen">
        <div
          v-if="unitCost !== null"
          class="border-ligne space-y-2 rounded-lg border bg-sable p-3 text-sm"
        >
          <div class="flex items-center justify-between gap-2" data-test="cost-line">
            <span class="text-texte font-semibold">{{ t('trips.assignCustomer.costLine') }}</span>
            <span class="flex items-center gap-2">
              <span class="text-texte font-semibold">{{ formatUnitMoney(unitCost) }}</span>
              <button
                type="button"
                data-test="cost-eye"
                class="text-texte-2 rounded p-1 hover:bg-white"
                :aria-label="t('trips.assignCustomer.showCostDetails')"
                :aria-expanded="showCostDetails"
                @click="showCostDetails = !showCostDetails"
              >
                <svg
                  viewBox="0 0 24 24"
                  class="h-5 w-5"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  aria-hidden="true"
                >
                  <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              </button>
            </span>
          </div>
          <dl v-if="showCostDetails" class="divide-ligne divide-y">
            <div
              v-for="row in componentRows"
              :key="row.label"
              class="flex items-center justify-between py-1.5"
            >
              <dt class="text-texte-2">{{ row.label }}</dt>
              <dd class="text-texte font-medium">{{ formatUnitMoney(row.value) }}</dd>
            </div>
          </dl>
        </div>

        <label class="block space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('trips.assignCustomer.sellingPrice')
          }}</span>
          <input
            v-model="unitPrice"
            data-test="unit-price"
            type="number"
            step="0.0001"
            min="0"
            :class="inputClass"
          />
        </label>
        <p
          v-if="benefit !== null"
          class="text-sm font-medium"
          :class="isLoss ? 'text-critique' : benefit === 0 ? 'text-texte' : 'text-livre'"
        >
          {{ resultText }}
        </p>

        <div v-if="isLoss" class="border-critique bg-critique-tint space-y-2 rounded-lg border p-3">
          <p class="text-critique-texte text-sm font-medium">
            {{ t('trips.delivery.lossWarning') }}
          </p>
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

        <div class="space-y-3">
          <label class="flex items-center gap-2 text-sm font-medium">
            <input
              v-model="quantityNow"
              data-test="quantity-now"
              type="checkbox"
              class="border-ligne-forte accent-orange h-5 w-5 rounded"
            />
            {{ t('trips.assignCustomer.quantityNow') }}
          </label>
          <p v-if="!quantityNow" class="text-texte-3 text-xs">
            {{ t('trips.assignCustomer.quantityLater') }}
          </p>
          <template v-else>
            <label v-for="trip in selectedTrips" :key="trip.id" class="block space-y-1.5">
              <span class="text-texte-2 text-sm font-medium">{{
                t('trips.assignCustomer.receivedQuantity', { reference: trip.reference })
              }}</span>
              <input
                :value="quantityFor(trip.id)"
                :data-test="`qty-${trip.id}`"
                type="number"
                step="1"
                min="0"
                :max="wholeLitres(costBases[trip.id]?.quantity)"
                :class="inputClass"
                @beforeinput="blockNonDigitInput"
                @input="quantities[trip.id] = ($event.target as HTMLInputElement).value"
              />
              <LossEstimate
                v-if="costBases[trip.id]"
                :quantity-loaded="costBases[trip.id]!.quantity"
                :received-quantity="quantityFor(trip.id)"
              />
            </label>
            <div v-if="isWalkIn" class="space-y-2">
              <p class="text-sm font-semibold">{{ t('trips.assignCustomer.paymentTitle') }}</p>
              <p class="text-texte-3 text-xs">{{ t('trips.assignCustomer.paymentHint') }}</p>
              <PaymentAccountPicker v-model="payment" />
            </div>
          </template>
        </div>
      </template>

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
          {{
            saving
              ? t('trips.assignCustomer.saving')
              : quantityNow
                ? t('trips.assignCustomer.confirmAndInvoice')
                : t('trips.assignCustomer.assignLater')
          }}
        </Button>
      </div>
    </form>
  </div>
</template>
