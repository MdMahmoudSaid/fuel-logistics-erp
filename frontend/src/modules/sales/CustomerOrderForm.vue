<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { customerOrderResource, fetchCustomerOrderTrips } from './api'
import { MANUALLY_SETTABLE_STATUSES } from './types'
import type { CustomerOrder, CustomerOrderStatus, CustomerBrief, ProductBrief } from './types'
import type { Trip, TripStatus } from '@/modules/trips/types'
import { useTripStatusLabel } from '@/modules/trips/tripStatusLabels'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const tripStatusLabel = useTripStatusLabel()

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
    error.value = t('sales.orderForm.saveError')
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

function badgeVariant(status: TripStatus) {
  if (status === 'DELIVERED' || status === 'COMPLETED') return 'livre' as const
  if (status === 'BLOCKED' || status === 'CANCELLED') return 'critique' as const
  return 'transit' as const
}
</script>

<template>
  <div class="max-w-3xl space-y-6">
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">
      {{
        isNew
          ? t('sales.orderForm.newTitle')
          : t('sales.orderForm.editTitle', { name: order?.customer_detail?.name ?? '' })
      }}
    </h1>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <div v-if="order" class="border-ligne space-y-2 rounded-xl border bg-surface p-4">
      <h2 class="font-display text-sm font-semibold uppercase">{{ t('sales.orderForm.progress') }}</h2>
      <div class="text-texte-2 space-y-2 text-xs">
        <div class="space-y-0.5">
          <div class="flex justify-between">
            <span>{{ t('sales.orderForm.assigned') }}</span>
            <span>{{ Number(order.assigned_quantity).toLocaleString() }} L</span>
          </div>
          <div class="bg-ligne h-2 w-full overflow-hidden rounded-full">
            <div class="bg-texte-3 h-full" :style="{ width: assignedPct + '%' }" />
          </div>
        </div>
        <div class="space-y-0.5">
          <div class="flex justify-between">
            <span>{{ t('sales.orderForm.loaded') }}</span>
            <span>{{ Number(order.loaded_quantity).toLocaleString() }} L</span>
          </div>
          <div class="bg-ligne h-2 w-full overflow-hidden rounded-full">
            <div class="bg-transit h-full" :style="{ width: loadedPct + '%' }" />
          </div>
        </div>
        <div class="space-y-0.5">
          <div class="flex justify-between">
            <span>{{ t('sales.orderForm.delivered') }}</span>
            <span>{{ Number(order.delivered_quantity).toLocaleString() }} L</span>
          </div>
          <div class="bg-ligne h-2 w-full overflow-hidden rounded-full">
            <div class="bg-livre h-full" :style="{ width: deliveredPct + '%' }" />
          </div>
        </div>
      </div>
      <p class="text-texte-2 pt-1 text-sm">
        {{ t('sales.orderForm.ordered') }}
        <span class="text-texte font-medium">{{ ordered.toLocaleString() }} L</span>
        · {{ t('sales.orderForm.remaining') }}
        <span class="text-texte font-medium"
          >{{ Number(order.remaining_quantity).toLocaleString() }} L</span
        >
      </p>
    </div>

    <form
      class="border-ligne grid grid-cols-2 gap-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="customer">{{
          t('sales.orderForm.customer')
        }}</label>
        <select
          id="customer"
          v-model="form.customer"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option value="" disabled>{{ t('sales.orderForm.selectCustomer') }}</option>
          <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="product">{{
          t('sales.orderForm.product')
        }}</label>
        <select
          id="product"
          v-model="form.product"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option value="" disabled>{{ t('sales.orderForm.selectProduct') }}</option>
          <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="quantity_ordered">{{
          t('sales.orderForm.quantityOrdered')
        }}</label>
        <input
          id="quantity_ordered"
          v-model="form.quantity_ordered"
          type="number"
          step="0.01"
          min="0.01"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="expected_price">{{
          t('sales.orderForm.expectedPrice')
        }}</label>
        <input
          id="expected_price"
          v-model="form.expected_price"
          type="number"
          step="0.0001"
          min="0"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="status">{{
          t('sales.orderForm.status')
        }}</label>
        <select
          v-if="statusIsManuallyEditable"
          id="status"
          v-model="form.status"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option v-for="s in MANUALLY_SETTABLE_STATUSES" :key="s" :value="s">
            {{ t(`customerOrderStatus.${s}`) }}
          </option>
        </select>
        <p v-else class="text-texte-2 rounded-lg border border-transparent px-3.5 py-2.5 text-sm">
          {{ t(`customerOrderStatus.${form.status}`) }}
          <span class="text-texte-3 text-xs">{{ t('sales.orderForm.computedFromTrips') }}</span>
        </p>
      </div>

      <div class="col-span-2 space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="notes">{{
          t('sales.orderForm.notes')
        }}</label>
        <textarea
          id="notes"
          v-model="form.notes"
          rows="2"
          class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>

      <div class="col-span-2 flex justify-end gap-2 pt-2">
        <Button variant="ghost" type="button" @click="router.push({ name: 'customer-orders' })">
          {{ t('sales.orderForm.back') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('sales.orderForm.saving') : t('sales.orderForm.save') }}
        </Button>
      </div>
    </form>

    <section v-if="!isNew" class="border-ligne space-y-3 rounded-xl border bg-surface p-6">
      <div class="flex items-center justify-between">
        <h2 class="font-display text-lg leading-none font-semibold uppercase">
          {{ t('sales.orderForm.trips') }}
        </h2>
        <Button variant="primary" @click="goToNewTrip">
          {{ t('sales.orderForm.newTrip') }}
        </Button>
      </div>

      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-2 py-1.5 font-medium">{{ t('sales.orderForm.table.reference') }}</th>
            <th class="px-2 py-1.5 font-medium">{{ t('sales.orderForm.table.truck') }}</th>
            <th class="px-2 py-1.5 font-medium text-right">
              {{ t('sales.orderForm.table.quantity') }}
            </th>
            <th class="px-2 py-1.5 font-medium">{{ t('sales.orderForm.table.status') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="trip in trips"
            :key="trip.id"
            class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
            @click="router.push({ name: 'trip-detail', params: { id: trip.id } })"
          >
            <td class="text-texte px-2 py-1.5 font-medium">{{ trip.reference }}</td>
            <td class="px-2 py-1.5">{{ trip.truck_detail?.internal_id }}</td>
            <td class="px-2 py-1.5 text-right">
              {{ Number(trip.quantity_loaded).toLocaleString() }}
            </td>
            <td class="px-2 py-1.5">
              <Badge :variant="badgeVariant(trip.status)">{{ tripStatusLabel(trip.status) }}</Badge>
            </td>
          </tr>
          <tr v-if="!trips.length">
            <td colspan="4" class="text-texte-3 px-2 py-4 text-center">
              {{ t('sales.orderForm.noTrips') }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
