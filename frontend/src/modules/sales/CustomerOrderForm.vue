<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { customerOrderResource, fetchCustomerOrderTrips } from './api'
import { MANUALLY_SETTABLE_STATUSES } from './types'
import type { CustomerOrder, CustomerOrderStatus, CustomerBrief, ProductBrief } from './types'
import type { Trip } from '@/modules/trips/types'

const route = useRoute()
const router = useRouter()

const orderId = computed(() => (route.params.id ? Number(route.params.id) : null))
const isNew = computed(() => orderId.value === null)

const customers = ref<CustomerBrief[]>([])
const products = ref<ProductBrief[]>([])
const order = ref<CustomerOrder | null>(null)
const trips = ref<Trip[]>([])

const form = ref({
  customer: '',
  product: '',
  quantity_ordered: '',
  expected_price: '',
  status: 'DRAFT' as CustomerOrderStatus,
  notes: '',
})

const saving = ref(false)
const error = ref('')

const customerResource = createResourceApi<CustomerBrief>('/customers/')
const productResource = createResourceApi<ProductBrief>('/products/')

// PARTIALLY_ASSIGNED/IN_PROGRESS/PARTIALLY_DELIVERED/DELIVERED are derived
// from trip progress by CustomerOrderService.recompute_status() and rejected
// by the API if set directly — only offer the manual states in the select.
const statusIsManuallyEditable = computed(
  () => isNew.value || MANUALLY_SETTABLE_STATUSES.includes(form.value.status),
)

async function loadOrder() {
  if (orderId.value === null) return
  order.value = await customerOrderResource.get!(orderId.value)
  form.value = {
    customer: String(order.value.customer),
    product: String(order.value.product),
    quantity_ordered: order.value.quantity_ordered,
    expected_price: order.value.expected_price ?? '',
    status: order.value.status,
    notes: order.value.notes,
  }
  trips.value = await fetchCustomerOrderTrips(orderId.value)
}

onMounted(async () => {
  const [customerData, productData] = await Promise.all([
    customerResource.list(),
    productResource.list(),
  ])
  customers.value = customerData.results
  products.value = productData.results
  await loadOrder()
})

async function onSubmit() {
  saving.value = true
  error.value = ''
  const payload: Partial<CustomerOrder> = {
    customer: Number(form.value.customer),
    product: Number(form.value.product),
    quantity_ordered: form.value.quantity_ordered,
    expected_price: form.value.expected_price || null,
    notes: form.value.notes,
  }
  if (statusIsManuallyEditable.value) payload.status = form.value.status

  try {
    if (isNew.value) {
      const created = await customerOrderResource.create(payload)
      router.replace({ name: 'customer-order-detail', params: { id: created.id } })
    } else {
      order.value = await customerOrderResource.update(orderId.value!, payload)
      form.value.status = order.value.status
    }
  } catch {
    error.value = 'Could not save — check the fields and your permissions.'
  } finally {
    saving.value = false
  }
}

function goToNewTrip() {
  router.push({ name: 'trip-new', query: { customer_order: String(orderId.value) } })
}

// --- Progress bar: Ordered / Assigned / Loaded / Delivered (plan Etape 9) ---
const ordered = computed(() => Number(order.value?.quantity_ordered ?? 0))
function pct(value: number) {
  if (ordered.value <= 0) return 0
  return Math.max(0, Math.min(100, (value / ordered.value) * 100))
}
const assignedPct = computed(() => pct(Number(order.value?.assigned_quantity ?? 0)))
const loadedPct = computed(() => pct(Number(order.value?.loaded_quantity ?? 0)))
const deliveredPct = computed(() => pct(Number(order.value?.delivered_quantity ?? 0)))

const TRIP_STATUS_BADGE: Record<string, string> = {
  ASSIGNED: 'bg-slate-100 text-slate-600',
  COMPLETED: 'bg-emerald-100 text-emerald-700',
  DELIVERED: 'bg-emerald-100 text-emerald-700',
  CANCELLED: 'bg-red-100 text-red-700',
  BLOCKED: 'bg-red-100 text-red-700',
}
</script>

<template>
  <div class="max-w-3xl space-y-6">
    <h2 class="text-lg font-semibold text-slate-800">
      {{ isNew ? 'New Customer Order' : `Order for ${order?.customer_detail?.name ?? ''}` }}
    </h2>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <div v-if="order" class="space-y-2 rounded border border-slate-200 bg-white p-4">
      <h3 class="text-sm font-semibold text-slate-700">Progress</h3>
      <div class="space-y-2 text-xs text-slate-500">
        <div class="space-y-0.5">
          <div class="flex justify-between">
            <span>Assigned</span>
            <span>{{ Number(order.assigned_quantity).toLocaleString() }} L</span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div class="h-full bg-slate-500" :style="{ width: assignedPct + '%' }" />
          </div>
        </div>
        <div class="space-y-0.5">
          <div class="flex justify-between">
            <span>Loaded</span>
            <span>{{ Number(order.loaded_quantity).toLocaleString() }} L</span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div class="h-full bg-sky-500" :style="{ width: loadedPct + '%' }" />
          </div>
        </div>
        <div class="space-y-0.5">
          <div class="flex justify-between">
            <span>Delivered</span>
            <span>{{ Number(order.delivered_quantity).toLocaleString() }} L</span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div class="h-full bg-emerald-500" :style="{ width: deliveredPct + '%' }" />
          </div>
        </div>
      </div>
      <p class="pt-1 text-sm text-slate-600">
        Ordered <span class="font-medium text-slate-800">{{ ordered.toLocaleString() }} L</span>
        · Remaining
        <span class="font-medium text-slate-800"
          >{{ Number(order.remaining_quantity).toLocaleString() }} L</span
        >
      </p>
    </div>

    <form class="grid grid-cols-2 gap-4 rounded border bg-white p-4" @submit.prevent="onSubmit">
      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="customer">Customer</label>
        <select
          id="customer"
          v-model="form.customer"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="" disabled>Select a customer</option>
          <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="product">Product</label>
        <select
          id="product"
          v-model="form.product"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="" disabled>Select a product</option>
          <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="quantity_ordered"
          >Quantity ordered (L)</label
        >
        <input
          id="quantity_ordered"
          v-model="form.quantity_ordered"
          type="number"
          step="0.01"
          min="0.01"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="expected_price"
          >Expected price / L</label
        >
        <input
          id="expected_price"
          v-model="form.expected_price"
          type="number"
          step="0.0001"
          min="0"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="status">Status</label>
        <select
          v-if="statusIsManuallyEditable"
          id="status"
          v-model="form.status"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option v-for="s in MANUALLY_SETTABLE_STATUSES" :key="s" :value="s">{{ s }}</option>
        </select>
        <p v-else class="rounded border border-transparent px-3 py-2 text-sm text-slate-600">
          {{ form.status }}
          <span class="text-xs text-slate-400">(computed from trip progress)</span>
        </p>
      </div>

      <div class="col-span-2 space-y-1">
        <label class="text-sm font-medium text-slate-600" for="notes">Notes</label>
        <textarea
          id="notes"
          v-model="form.notes"
          rows="2"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="col-span-2 flex justify-end gap-2 pt-2">
        <button
          type="button"
          class="px-3 py-2 text-sm text-slate-500"
          @click="router.push({ name: 'customer-orders' })"
        >
          Back
        </button>
        <button
          type="submit"
          :disabled="saving"
          class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
    </form>

    <section v-if="!isNew" class="space-y-3 rounded border bg-white p-4">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-semibold text-slate-800">Trips</h3>
        <button
          class="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white"
          @click="goToNewTrip"
        >
          New Trip
        </button>
      </div>

      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-b text-slate-500">
            <th class="px-2 py-1.5 font-medium">Reference</th>
            <th class="px-2 py-1.5 font-medium">Truck</th>
            <th class="px-2 py-1.5 font-medium text-right">Quantity (L)</th>
            <th class="px-2 py-1.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="trip in trips"
            :key="trip.id"
            class="cursor-pointer border-b last:border-0 hover:bg-slate-50"
            @click="router.push({ name: 'trip-detail', params: { id: trip.id } })"
          >
            <td class="px-2 py-1.5 font-medium text-slate-800">{{ trip.reference }}</td>
            <td class="px-2 py-1.5">{{ trip.truck_detail?.internal_id }}</td>
            <td class="px-2 py-1.5 text-right">
              {{ Number(trip.quantity_loaded).toLocaleString() }}
            </td>
            <td class="px-2 py-1.5">
              <span
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :class="TRIP_STATUS_BADGE[trip.status] ?? 'bg-amber-100 text-amber-700'"
              >
                {{ trip.status }}
              </span>
            </td>
          </tr>
          <tr v-if="!trips.length">
            <td colspan="4" class="px-2 py-4 text-center text-slate-400">No trips yet.</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
