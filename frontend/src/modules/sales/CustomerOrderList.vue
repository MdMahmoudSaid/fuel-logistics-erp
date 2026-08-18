<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { customerOrderResource } from './api'
import type { CustomerOrder, CustomerBrief, ProductBrief } from './types'

const router = useRouter()

const orders = ref<CustomerOrder[]>([])
const customers = ref<CustomerBrief[]>([])
const products = ref<ProductBrief[]>([])
const loading = ref(false)
const error = ref('')

const filters = ref({ customer: '', product: '', status: '' })

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

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-slate-100 text-slate-600',
  CONFIRMED: 'bg-sky-100 text-sky-700',
  PARTIALLY_ASSIGNED: 'bg-amber-100 text-amber-700',
  IN_PROGRESS: 'bg-amber-100 text-amber-700',
  PARTIALLY_DELIVERED: 'bg-indigo-100 text-indigo-700',
  DELIVERED: 'bg-emerald-100 text-emerald-700',
  CLOSED: 'bg-slate-100 text-slate-600',
  CANCELLED: 'bg-red-100 text-red-700',
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">Customer Orders</h2>
      <button
        class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white"
        @click="goToNew"
      >
        New Order
      </button>
    </div>

    <div class="flex flex-wrap gap-3 rounded border bg-white p-3">
      <select
        v-model="filters.customer"
        class="rounded border border-slate-300 px-2 py-1.5 text-sm"
        @change="loadOrders"
      >
        <option value="">All customers</option>
        <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
      </select>
      <select
        v-model="filters.product"
        class="rounded border border-slate-300 px-2 py-1.5 text-sm"
        @change="loadOrders"
      >
        <option value="">All products</option>
        <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <select
        v-model="filters.status"
        class="rounded border border-slate-300 px-2 py-1.5 text-sm"
        @change="loadOrders"
      >
        <option value="">All statuses</option>
        <option value="DRAFT">Draft</option>
        <option value="CONFIRMED">Confirmed</option>
        <option value="PARTIALLY_ASSIGNED">Partially assigned</option>
        <option value="IN_PROGRESS">In progress</option>
        <option value="PARTIALLY_DELIVERED">Partially delivered</option>
        <option value="DELIVERED">Delivered</option>
        <option value="CLOSED">Closed</option>
        <option value="CANCELLED">Cancelled</option>
      </select>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <div class="overflow-x-auto rounded border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-b text-slate-500">
            <th class="px-3 py-2 font-medium">Customer</th>
            <th class="px-3 py-2 font-medium">Product</th>
            <th class="px-3 py-2 font-medium text-right">Ordered (L)</th>
            <th class="px-3 py-2 font-medium text-right">Assigned (L)</th>
            <th class="px-3 py-2 font-medium text-right">Delivered (L)</th>
            <th class="px-3 py-2 font-medium text-right">Remaining (L)</th>
            <th class="px-3 py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="order in orders"
            :key="order.id"
            class="cursor-pointer border-b last:border-0 hover:bg-slate-50"
            @click="goToDetail(order)"
          >
            <td class="px-3 py-2 font-medium text-slate-800">{{ order.customer_detail?.name }}</td>
            <td class="px-3 py-2">{{ order.product_detail?.name }}</td>
            <td class="px-3 py-2 text-right">
              {{ Number(order.quantity_ordered).toLocaleString() }}
            </td>
            <td class="px-3 py-2 text-right">
              {{ Number(order.assigned_quantity).toLocaleString() }}
            </td>
            <td class="px-3 py-2 text-right">
              {{ Number(order.delivered_quantity).toLocaleString() }}
            </td>
            <td class="px-3 py-2 text-right font-medium">
              {{ Number(order.remaining_quantity).toLocaleString() }}
            </td>
            <td class="px-3 py-2">
              <span
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :class="STATUS_BADGE[order.status]"
              >
                {{ order.status }}
              </span>
            </td>
          </tr>
          <tr v-if="!loading && orders.length === 0">
            <td colspan="7" class="px-3 py-6 text-center text-slate-400">
              No customer orders yet.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
