<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { useAuthStore } from '@/stores/auth'
import { cessionLetterResource, supplierOrderResource } from '@/modules/purchasing/api'
import type { CessionLetter, SupplierOrder } from '@/modules/purchasing/types'
import { customerOrderResource } from '@/modules/sales/api'
import type { CustomerOrder } from '@/modules/sales/types'
import { tripResource } from './api'
import type { Trip, TruckBrief, TransporterBrief, DriverBrief, CustomerBrief } from './types'
import { translateApiError, extractFieldErrors } from '@/i18n/apiErrors'
import Button from '@/components/ui/Button.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t, te } = useI18n()

function truckStatusLabel(status: string): string {
  const key = `truckStatus.${status}`
  return te(key) ? t(key) : status
}

const prefilledOrderId = computed(() =>
  route.query.customer_order ? Number(route.query.customer_order) : null,
)

const cessions = ref<CessionLetter[]>([])
const selectedCession = ref<CessionLetter | null>(null)
const selectedSupplierOrder = ref<SupplierOrder | null>(null)
const selectedTruck = ref<TruckBrief | null>(null)

const trucks = ref<TruckBrief[]>([])
const transporters = ref<TransporterBrief[]>([])
const drivers = ref<DriverBrief[]>([])
const customers = ref<CustomerBrief[]>([])
const customerOrders = ref<CustomerOrder[]>([])

// Truck & transporter pickers filter to available-only by default (plan
// Etape 9). Only an Admin can flip this to see occupied ones and force an
// assignment — mirrors the Admin-only override the backend enforces
// regardless (backend/apps/trips/serializers.py._validate_truck_availability).
const isAdmin = computed(() => auth.user?.role_detail?.name === 'Admin')
const showBusyTrucks = ref(false)

const trucksResource = createResourceApi<TruckBrief>('/trucks/')
const transporterResource = createResourceApi<TransporterBrief>('/transporters/')
const driverResource = createResourceApi<DriverBrief>('/drivers/')
const customerResource = createResourceApi<CustomerBrief>('/customers/')

async function loadTransporters() {
  const params = showBusyTrucks.value ? {} : { available: true }
  const data = await transporterResource.list(params)
  transporters.value = data.results
}

const form = ref({
  cession_letter: '',
  truck: '',
  transporter: '',
  driver: '',
  quantity_loaded: '',
  loading_date: '',
  bl_reference: '',
  client: '',
  customer_order: prefilledOrderId.value ? String(prefilledOrderId.value) : '',
  notes: '',
})

const saving = ref(false)
const error = ref('')
const fieldErrors = ref<Record<string, string>>({})

async function loadTrucks() {
  const params = showBusyTrucks.value ? {} : { available: true }
  const data = await trucksResource.list(params)
  trucks.value = data.results
}

watch(showBusyTrucks, () => Promise.all([loadTrucks(), loadTransporters()]))

async function onCessionChange() {
  const cession = cessions.value.find((c) => c.id === Number(form.value.cession_letter)) ?? null
  selectedCession.value = cession
  selectedSupplierOrder.value = cession
    ? await supplierOrderResource.get!(cession.supplier_order)
    : null
}

function onTruckChange() {
  const truck = trucks.value.find((t) => t.id === Number(form.value.truck))
  selectedTruck.value = truck ?? null
  if (!truck) return
  // Convenience prefill only — the transporter/driver fields stay editable
  // (roadmap/phase_3_truck_operations.md: transporter "defaults from
  // truck.owner_transporter", but the backend requires it explicitly).
  if (truck.owner_transporter) form.value.transporter = String(truck.owner_transporter)
  if (truck.default_driver) form.value.driver = String(truck.default_driver)
}

// Orders still open to receiving more trips — hides CLOSED/CANCELLED/
// DELIVERED from the picker when the form wasn't reached from a specific
// order's "New Trip" button.
const ASSIGNABLE_ORDER_STATUSES = [
  'CONFIRMED',
  'PARTIALLY_ASSIGNED',
  'IN_PROGRESS',
  'PARTIALLY_DELIVERED',
]

onMounted(async () => {
  const [cessionData, driverData, customerData] = await Promise.all([
    cessionLetterResource.list({ status: 'ACTIVE' }),
    driverResource.list(),
    customerResource.list(),
  ])
  cessions.value = cessionData.results
  drivers.value = driverData.results
  customers.value = customerData.results
  await Promise.all([loadTrucks(), loadTransporters()])

  if (!prefilledOrderId.value) {
    const orderData = await customerOrderResource.list()
    customerOrders.value = orderData.results.filter((o) =>
      ASSIGNABLE_ORDER_STATUSES.includes(o.status),
    )
  }
})

// --- Live cession-remaining bar (same idiom as CessionLetterForm's
// allocation bar, guarding the same rule server-side under a row lock:
// SupplierStockService.validate_and_lock_cession_quantity) ---
const cessionAuthorized = computed(() => Number(selectedCession.value?.authorized_quantity ?? 0))
const cessionRemaining = computed(() => Number(selectedCession.value?.remaining_quantity ?? 0))
const requested = computed(() => Number(form.value.quantity_loaded) || 0)
const isOverLimit = computed(() => requested.value > cessionRemaining.value)

function pct(value: number) {
  if (cessionAuthorized.value <= 0) return 0
  return Math.max(0, Math.min(100, (value / cessionAuthorized.value) * 100))
}
const remainingPct = computed(() => pct(cessionRemaining.value))
const requestedPct = computed(() => pct(Math.min(requested.value, cessionRemaining.value)))

// --- Truck capacity guard: quantity_loaded must never exceed the selected
// truck's capacity_litres, checked live client-side and enforced again by
// TripSerializer._validate_truck_capacity server-side. ---
const truckCapacity = computed(() => Number(selectedTruck.value?.capacity_litres ?? 0))
const exceedsCapacity = computed(
  () => selectedTruck.value != null && requested.value > truckCapacity.value,
)
const capacityErrorMessage = computed(() =>
  t('trips.newForm.exceedsCapacity', {
    quantity: requested.value.toLocaleString(),
    capacity: truckCapacity.value.toLocaleString(),
  }),
)

async function onSubmit() {
  if (!selectedCession.value || !selectedSupplierOrder.value) {
    error.value = t('trips.newForm.selectCessionFirst')
    return
  }
  if (exceedsCapacity.value) {
    fieldErrors.value = { ...fieldErrors.value, quantity_loaded: capacityErrorMessage.value }
    return
  }
  saving.value = true
  error.value = ''
  fieldErrors.value = {}
  const payload: Partial<Trip> = {
    truck: Number(form.value.truck),
    transporter: Number(form.value.transporter),
    driver: form.value.driver ? Number(form.value.driver) : null,
    supplier: selectedSupplierOrder.value.supplier,
    supplier_order: selectedSupplierOrder.value.id,
    cession_letter: selectedCession.value.id,
    product: selectedSupplierOrder.value.product,
    quantity_loaded: form.value.quantity_loaded,
    client: form.value.client ? Number(form.value.client) : null,
    customer_order: form.value.customer_order ? Number(form.value.customer_order) : null,
    loading_date: form.value.loading_date,
    bl_reference: form.value.bl_reference,
    notes: form.value.notes,
    force: showBusyTrucks.value,
  }
  try {
    const created = await tripResource.create(payload)
    router.push({ name: 'trip-detail', params: { id: created.id } })
  } catch (e) {
    const response = (e as { response?: { status?: number; data?: Record<string, unknown> } })
      ?.response
    const body = response?.status === 400 ? response.data : undefined
    fieldErrors.value = extractFieldErrors(body)
    const generic = body?.detail ?? body?.non_field_errors
    const genericMessage = Array.isArray(generic) ? generic[0] : generic
    error.value =
      translateApiError(typeof genericMessage === 'string' ? genericMessage : undefined) ??
      (Object.keys(fieldErrors.value).length ? '' : t('trips.newForm.saveError'))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="max-w-3xl space-y-6">
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">
      {{ t('trips.newForm.title') }}
    </h1>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <form
      class="border-ligne space-y-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="cession_letter">{{
          t('trips.newForm.cessionLetter')
        }}</label>
        <select
          id="cession_letter"
          v-model="form.cession_letter"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          @change="onCessionChange"
        >
          <option value="" disabled>{{ t('trips.newForm.selectCessionLetter') }}</option>
          <option v-for="c in cessions" :key="c.id" :value="c.id">
            {{ c.reference }} ({{ Number(c.remaining_quantity).toLocaleString() }}
            {{ t('purchasing.cessionForm.remainingSuffix') }})
          </option>
        </select>
        <p v-if="fieldErrors.cession_letter" class="text-critique text-xs">
          {{ fieldErrors.cession_letter }}
        </p>
      </div>

      <div v-if="selectedCession" class="border-ligne space-y-2 rounded-lg border bg-sable p-3">
        <div class="text-texte-2 flex justify-between text-xs">
          <span>{{ t('trips.newForm.cessionAuthorized') }} {{ cessionAuthorized.toLocaleString() }} L</span>
          <span>{{ t('trips.newForm.remaining') }} {{ cessionRemaining.toLocaleString() }} L</span>
          <span :class="isOverLimit ? 'text-critique font-semibold' : ''">
            {{ t('trips.newForm.requested') }} {{ requested.toLocaleString() }} L
          </span>
        </div>
        <div class="bg-ligne flex h-3 w-full overflow-hidden rounded-full">
          <div class="bg-texte-3" :style="{ width: 100 - remainingPct + '%' }" />
          <div
            :class="isOverLimit ? 'bg-critique' : 'bg-livre'"
            :style="{ width: requestedPct + '%' }"
          />
        </div>
        <p v-if="isOverLimit" class="text-critique text-sm font-medium">
          {{ t('trips.newForm.exceedsRemaining') }}
        </p>
      </div>

      <div v-if="isAdmin" class="text-texte-2 flex items-center gap-2 text-sm">
        <input
          id="show_busy"
          v-model="showBusyTrucks"
          type="checkbox"
          class="border-ligne-forte accent-orange h-5 w-5 rounded"
        />
        <label for="show_busy">{{ t('trips.newForm.showBusyTrucks') }}</label>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="truck">{{
            t('trips.newForm.truck')
          }}</label>
          <select
            id="truck"
            v-model="form.truck"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            @change="onTruckChange"
          >
            <option value="" disabled>{{ t('trips.newForm.selectTruck') }}</option>
            <option v-for="truck in trucks" :key="truck.id" :value="truck.id">
              {{ truck.internal_id }}
              <template v-if="truck.status !== 'AVAILABLE'">
                {{ ' ' + t('trips.newForm.occupied', { status: truckStatusLabel(truck.status) }) }}
              </template>
            </option>
          </select>
          <p v-if="fieldErrors.truck" class="text-critique text-xs">{{ fieldErrors.truck }}</p>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="transporter">{{
            t('trips.newForm.transporter')
          }}</label>
          <select
            id="transporter"
            v-model="form.transporter"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('trips.newForm.selectTransporter') }}</option>
            <option v-for="tr in transporters" :key="tr.id" :value="tr.id">{{ tr.name }}</option>
          </select>
          <p v-if="fieldErrors.transporter" class="text-critique text-xs">
            {{ fieldErrors.transporter }}
          </p>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="driver">{{
            t('trips.newForm.driver')
          }}</label>
          <select
            id="driver"
            v-model="form.driver"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="">{{ t('trips.newForm.noDriver') }}</option>
            <option v-for="d in drivers" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
          <p v-if="fieldErrors.driver" class="text-critique text-xs">{{ fieldErrors.driver }}</p>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="quantity_loaded">{{
            t('trips.newForm.quantityLoaded')
          }}</label>
          <input
            id="quantity_loaded"
            v-model="form.quantity_loaded"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            :class="isOverLimit || exceedsCapacity ? 'border-critique' : ''"
          />
          <p v-if="exceedsCapacity" class="text-critique text-xs">
            {{ capacityErrorMessage }}
          </p>
          <p v-else-if="fieldErrors.quantity_loaded" class="text-critique text-xs">
            {{ fieldErrors.quantity_loaded }}
          </p>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="loading_date">{{
            t('trips.newForm.loadingDate')
          }}</label>
          <input
            id="loading_date"
            v-model="form.loading_date"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
          <p v-if="fieldErrors.loading_date" class="text-critique text-xs">
            {{ fieldErrors.loading_date }}
          </p>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="bl_reference">{{
            t('trips.newForm.blReference')
          }}</label>
          <input
            id="bl_reference"
            v-model="form.bl_reference"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
          <p class="text-texte-3 text-xs">{{ t('trips.newForm.blReferenceHint') }}</p>
          <p v-if="fieldErrors.bl_reference" class="text-critique text-xs">
            {{ fieldErrors.bl_reference }}
          </p>
        </div>
      </div>

      <div v-if="prefilledOrderId" class="text-texte-2 text-sm">
        {{ t('trips.newForm.againstCustomerOrder') }}
        <span class="text-texte font-medium">#{{ prefilledOrderId }}</span>
      </div>
      <div v-else class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="customer_order">{{
          t('trips.newForm.customerOrder')
        }}</label>
        <select
          id="customer_order"
          v-model="form.customer_order"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option value="">{{ t('trips.newForm.noCustomerOrder') }}</option>
          <option v-for="o in customerOrders" :key="o.id" :value="o.id">
            #{{ o.id }} — {{ o.customer_detail?.name }} ({{
              Number(o.remaining_quantity).toLocaleString()
            }}
            {{ t('purchasing.cessionForm.remainingSuffix') }})
          </option>
        </select>
        <p v-if="fieldErrors.customer_order" class="text-critique text-xs">
          {{ fieldErrors.customer_order }}
        </p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="client">{{
          t('trips.newForm.client')
        }}</label>
        <select
          id="client"
          v-model="form.client"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option value="">{{ t('trips.newForm.noClient') }}</option>
          <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <p v-if="fieldErrors.client" class="text-critique text-xs">{{ fieldErrors.client }}</p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="notes">{{
          t('trips.newForm.notes')
        }}</label>
        <textarea
          id="notes"
          v-model="form.notes"
          rows="2"
          class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p v-if="fieldErrors.notes" class="text-critique text-xs">{{ fieldErrors.notes }}</p>
      </div>

      <div class="flex justify-end gap-2 pt-2">
        <Button variant="ghost" type="button" @click="router.back()">
          {{ t('trips.newForm.back') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving" :disabled="exceedsCapacity">
          {{ saving ? t('trips.newForm.saving') : t('trips.newForm.createTrip') }}
        </Button>
      </div>
    </form>
  </div>
</template>
