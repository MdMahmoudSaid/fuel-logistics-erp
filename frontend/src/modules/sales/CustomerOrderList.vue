<script setup lang="ts">
// Vue hybride (docs/UI_REDESIGN_PLAN.md Etape 6.2) : tableau desktop
// (>=768px, chiffres Mono alignés à droite) / cartes empilées mobile
// (<768px), avec puces de filtre statut à défilement horizontal.
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { customerOrderResource } from './api'
import type { CustomerOrder, CustomerOrderStatus, CustomerBrief, ProductBrief } from './types'
import Chip from '@/components/ui/Chip.vue'
import Badge from '@/components/ui/Badge.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import Button from '@/components/ui/Button.vue'

const router = useRouter()

const orders = ref<CustomerOrder[]>([])
const customers = ref<CustomerBrief[]>([])
const products = ref<ProductBrief[]>([])
const loading = ref(false)
const error = ref('')

const filters = ref<{ customer: string; product: string; status: CustomerOrderStatus | '' }>({
  customer: '',
  product: '',
  status: '',
})

const STATUSES: CustomerOrderStatus[] = [
  'DRAFT',
  'CONFIRMED',
  'PARTIALLY_ASSIGNED',
  'IN_PROGRESS',
  'PARTIALLY_DELIVERED',
  'DELIVERED',
  'CLOSED',
  'CANCELLED',
]

const STATUS_LABEL: Record<CustomerOrderStatus, string> = {
  DRAFT: 'Draft',
  CONFIRMED: 'Confirmed',
  PARTIALLY_ASSIGNED: 'Partially assigned',
  IN_PROGRESS: 'In progress',
  PARTIALLY_DELIVERED: 'Partially delivered',
  DELIVERED: 'Delivered',
  CLOSED: 'Closed',
  CANCELLED: 'Cancelled',
}

function badgeVariant(status: CustomerOrderStatus) {
  if (status === 'DELIVERED' || status === 'CLOSED') return 'livre' as const
  if (status === 'CANCELLED') return 'critique' as const
  if (
    status === 'PARTIALLY_ASSIGNED' ||
    status === 'IN_PROGRESS' ||
    status === 'PARTIALLY_DELIVERED'
  )
    return 'ecart' as const
  return 'transit' as const
}

const customerResource = createResourceApi<CustomerBrief>('/customers/')
const productResource = createResourceApi<ProductBrief>('/products/')

async function loadOrders() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string> = {}
    if (filters.value.customer) params.customer = filters.value.customer
    if (filters.value.product) params.product = filters.value.product
    if (filters.value.status) params.status = filters.value.status
    const data = await customerOrderResource.list(params)
    orders.value = data.results
  } catch {
    error.value = 'Could not load customer orders.'
  } finally {
    loading.value = false
  }
}

function toggleStatus(status: CustomerOrderStatus) {
  filters.value.status = filters.value.status === status ? '' : status
  loadOrders()
}

function clearStatus() {
  filters.value.status = ''
  loadOrders()
}

onMounted(async () => {
  const [customerData, productData] = await Promise.all([
    customerResource.list(),
    productResource.list(),
  ])
  customers.value = customerData.results
  products.value = productData.results
  await loadOrders()
})

function goToNew() {
  router.push({ name: 'customer-order-new' })
}

function goToDetail(order: CustomerOrder) {
  router.push({ name: 'customer-order-detail', params: { id: order.id } })
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">Customer Orders</h1>
      <Button variant="primary" @click="goToNew">New Order</Button>
    </div>

    <div class="flex flex-wrap gap-3">
      <select
        v-model="filters.customer"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="loadOrders"
      >
        <option value="">All customers</option>
        <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
      </select>
      <select
        v-model="filters.product"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="loadOrders"
      >
        <option value="">All products</option>
        <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>

    <div class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      <Chip :active="filters.status === ''" @click="clearStatus">Tous</Chip>
      <Chip
        v-for="status in STATUSES"
        :key="status"
        :active="filters.status === status"
        @click="toggleStatus(status)"
      >
        {{ STATUS_LABEL[status] }}
      </Chip>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <!-- Desktop : tableau complet, chiffres Mono alignés à droite -->
    <div class="border-ligne hidden overflow-x-auto rounded-xl border bg-white md:block">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">Customer</th>
            <th class="px-3 py-2.5 font-medium">Product</th>
            <th class="px-3 py-2.5 text-right font-medium">Ordered (L)</th>
            <th class="px-3 py-2.5 text-right font-medium">Assigned (L)</th>
            <th class="px-3 py-2.5 text-right font-medium">Delivered (L)</th>
            <th class="px-3 py-2.5 text-right font-medium">Remaining (L)</th>
            <th class="px-3 py-2.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="order in orders"
            :key="order.id"
            class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
            @click="goToDetail(order)"
          >
            <td class="px-3 py-2.5 font-medium">{{ order.customer_detail?.name }}</td>
            <td class="px-3 py-2.5">{{ order.product_detail?.name }}</td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="Number(order.quantity_ordered).toLocaleString()" />
            </td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="Number(order.assigned_quantity).toLocaleString()" />
            </td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="Number(order.delivered_quantity).toLocaleString()" />
            </td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="Number(order.remaining_quantity).toLocaleString()" />
            </td>
            <td class="px-3 py-2.5">
              <Badge :variant="badgeVariant(order.status)">{{ STATUS_LABEL[order.status] }}</Badge>
            </td>
          </tr>
          <tr v-if="!loading && orders.length === 0">
            <td colspan="7" class="text-texte-3 px-3 py-8 text-center">No customer orders yet.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Mobile : cartes empilées -->
    <div class="space-y-3 md:hidden">
      <button
        v-for="order in orders"
        :key="order.id"
        type="button"
        class="border-ligne block w-full space-y-3 rounded-xl border bg-white p-4 text-left"
        @click="goToDetail(order)"
      >
        <div class="flex items-start justify-between gap-2">
          <div>
            <p class="font-medium">{{ order.customer_detail?.name }}</p>
            <p class="text-texte-2 text-xs">{{ order.product_detail?.name }}</p>
          </div>
          <Badge :variant="badgeVariant(order.status)">{{ STATUS_LABEL[order.status] }}</Badge>
        </div>
        <div class="grid grid-cols-3 gap-2 text-xs">
          <div>
            <p class="text-texte-3 uppercase">Ordered</p>
            <MonoValue :value="Number(order.quantity_ordered).toLocaleString()" align="left" />
          </div>
          <div>
            <p class="text-texte-3 uppercase">Delivered</p>
            <MonoValue :value="Number(order.delivered_quantity).toLocaleString()" align="left" />
          </div>
          <div>
            <p class="text-texte-3 uppercase">Remaining</p>
            <MonoValue :value="Number(order.remaining_quantity).toLocaleString()" align="left" />
          </div>
        </div>
      </button>
      <p
        v-if="!loading && orders.length === 0"
        class="text-texte-3 border-ligne rounded-xl border border-dashed p-6 text-center text-sm"
      >
        No customer orders yet.
      </p>
    </div>
  </div>
</template>
