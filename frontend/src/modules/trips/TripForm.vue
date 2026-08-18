<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { useAuthStore } from '@/stores/auth'
import { cessionLetterResource, supplierOrderResource } from '@/modules/purchasing/api'
import type { CessionLetter, SupplierOrder } from '@/modules/purchasing/types'
import { customerOrderResource } from '@/modules/sales/api'
import type { CustomerOrder } from '@/modules/sales/types'
import { tripResource } from './api'
import type { Trip, TruckBrief, TransporterBrief, DriverBrief, CustomerBrief } from './types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const prefilledOrderId = computed(() =>
  route.query.customer_order ? Number(route.query.customer_order) : null,
)

const cessions = ref<CessionLetter[]>([])
const selectedCession = ref<CessionLetter | null>(null)
const selectedSupplierOrder = ref<SupplierOrder | null>(null)

const trucks = ref<TruckBrief[]>([])
const transporters = ref<TransporterBrief[]>([])
const drivers = ref<DriverBrief[]>([])
const customers = ref<CustomerBrief[]>([])
const customerOrders = ref<CustomerOrder[]>([])

// Truck picker filters to AVAILABLE by default (plan Etape 9). Only an
// Admin can flip this to see occupied trucks and force an assignment —
// mirrors the Admin-only override the backend enforces regardless
// (backend/apps/trips/serializers.py._validate_truck_availability).
const isAdmin = computed(() => auth.user?.role_detail?.name === 'Admin')
const showBusyTrucks = ref(false)

const trucksResource = createResourceApi<TruckBrief>('/trucks/')
const transporterResource = createResourceApi<TransporterBrief>('/transporters/')
const driverResource = createResourceApi<DriverBrief>('/drivers/')
const customerResource = createResourceApi<CustomerBrief>('/customers/')

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

async function loadTrucks() {
  const params = showBusyTrucks.value ? {} : { status: 'AVAILABLE' }
  const data = await trucksResource.list(params)
  trucks.value = data.results
}

watch(showBusyTrucks, loadTrucks)

async function onCessionChange() {
  const cession = cessions.value.find((c) => c.id === Number(form.value.cession_letter)) ?? null
  selectedCession.value = cession
  selectedSupplierOrder.value = cession
    ? await supplierOrderResource.get!(cession.supplier_order)
    : null
}

function onTruckChange() {
  const truck = trucks.value.find((t) => t.id === Number(form.value.truck))
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
  const [cessionData, transporterData, driverData, customerData] = await Promise.all([
    cessionLetterResource.list({ status: 'ACTIVE' }),
    transporterResource.list(),
    driverResource.list(),
    customerResource.list(),
  ])
  cessions.value = cessionData.results
  transporters.value = transporterData.results
  drivers.value = driverData.results
  customers.value = customerData.results
  await loadTrucks()

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

async function onSubmit() {
  if (!selectedCession.value || !selectedSupplierOrder.value) {
    error.value = 'Select a cession letter first.'
    return
  }
  saving.value = true
  error.value = ''
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
    const data = (e as { response?: { data?: Record<string, string[] | string> } })?.response?.data
    const firstEntry = data ? Object.values(data)[0] : undefined
    const detail = Array.isArray(firstEntry) ? firstEntry[0] : firstEntry
    error.value = detail || 'Could not save — check the fields and your permissions.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="max-w-3xl space-y-6">
    <h2 class="text-lg font-semibold text-slate-800">New Trip (Loading)</h2>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <form class="space-y-4 rounded border bg-white p-4" @submit.prevent="onSubmit">
      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="cession_letter"
          >Cession letter</label
        >
        <select
          id="cession_letter"
          v-model="form.cession_letter"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          @change="onCessionChange"
        >
          <option value="" disabled>Select a cession letter</option>
          <option v-for="c in cessions" :key="c.id" :value="c.id">
            {{ c.reference }} ({{ Number(c.remaining_quantity).toLocaleString() }} L remaining)
          </option>
        </select>
      </div>

      <div v-if="selectedCession" class="space-y-2 rounded border border-slate-200 bg-slate-50 p-3">
        <div class="flex justify-between text-xs text-slate-500">
          <span>Cession authorized: {{ cessionAuthorized.toLocaleString() }} L</span>
          <span>Remaining: {{ cessionRemaining.toLocaleString() }} L</span>
          <span :class="isOverLimit ? 'font-semibold text-red-600' : ''">
            Requested: {{ requested.toLocaleString() }} L
          </span>
        </div>
        <div class="flex h-3 w-full overflow-hidden rounded-full bg-slate-200">
          <div class="bg-slate-300" :style="{ width: 100 - remainingPct + '%' }" />
          <div
            :class="isOverLimit ? 'bg-red-500' : 'bg-emerald-500'"
            :style="{ width: requestedPct + '%' }"
          />
        </div>
        <p v-if="isOverLimit" class="text-sm font-medium text-red-600">
          Exceeds the cession's remaining quantity. Reduce the requested quantity before saving.
        </p>
      </div>

      <div v-if="isAdmin" class="flex items-center gap-2 text-sm text-slate-600">
        <input id="show_busy" v-model="showBusyTrucks" type="checkbox" class="rounded" />
        <label for="show_busy">Show occupied trucks (Admin override — force assignment)</label>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="truck">Truck</label>
          <select
            id="truck"
            v-model="form.truck"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            @change="onTruckChange"
          >
            <option value="" disabled>Select a truck</option>
            <option v-for="t in trucks" :key="t.id" :value="t.id">
              {{ t.internal_id }}
              <template v-if="t.status !== 'AVAILABLE'"> (occupied — {{ t.status }})</template>
            </option>
          </select>
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="transporter">Transporter</label>
          <select
            id="transporter"
            v-model="form.transporter"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="" disabled>Select a transporter</option>
            <option v-for="tr in transporters" :key="tr.id" :value="tr.id">{{ tr.name }}</option>
          </select>
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="driver">Driver (optional)</label>
          <select
            id="driver"
            v-model="form.driver"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">No driver</option>
            <option v-for="d in drivers" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="quantity_loaded"
            >Quantity loaded (L)</label
          >
          <input
            id="quantity_loaded"
            v-model="form.quantity_loaded"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            :class="isOverLimit ? 'border-red-400' : ''"
          />
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="loading_date">Loading date</label>
          <input
            id="loading_date"
            v-model="form.loading_date"
            type="date"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="bl_reference">BL reference</label>
          <input
            id="bl_reference"
            v-model="form.bl_reference"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
      </div>

      <div v-if="prefilledOrderId" class="text-sm text-slate-600">
        Against customer order
        <span class="font-medium text-slate-800">#{{ prefilledOrderId }}</span>
      </div>
      <div v-else class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="customer_order"
          >Customer order (optional)</label
        >
        <select
          id="customer_order"
          v-model="form.customer_order"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">No customer order — direct sale</option>
          <option v-for="o in customerOrders" :key="o.id" :value="o.id">
            #{{ o.id }} — {{ o.customer_detail?.name }} ({{
              Number(o.remaining_quantity).toLocaleString()
            }}
            L remaining)
          </option>
        </select>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="client">Client (optional)</label>
        <select
          id="client"
          v-model="form.client"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">No client</option>
          <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
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

      <div class="flex justify-end gap-2 pt-2">
        <button type="button" class="px-3 py-2 text-sm text-slate-500" @click="router.back()">
          Back
        </button>
        <button
          type="submit"
          :disabled="saving"
          class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {{ saving ? 'Saving…' : 'Create Trip' }}
        </button>
      </div>
    </form>
  </div>
</template>
