<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { supplierOrderResource } from './api'
import type { SupplierOrder } from './types'
import type { SupplierBrief, ProductBrief } from './types'

const router = useRouter()

const orders = ref<SupplierOrder[]>([])
const suppliers = ref<SupplierBrief[]>([])
const products = ref<ProductBrief[]>([])
const loading = ref(false)
const error = ref('')

const filters = ref({ supplier: '', product: '', status: '' })

const supplierResource = createResourceApi<SupplierBrief>('/suppliers/')
const productResource = createResourceApi<ProductBrief>('/products/')

async function loadOrders() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string> = {}
    if (filters.value.supplier) params.supplier = filters.value.supplier
    if (filters.value.product) params.product = filters.value.product
    if (filters.value.status) params.status = filters.value.status
    const data = await supplierOrderResource.list(params)
    orders.value = data.results
  } catch {
    error.value = 'Could not load supplier orders.'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  const [supplierData, productData] = await Promise.all([
    supplierResource.list(),
    productResource.list(),
  ])
  suppliers.value = supplierData.results
  products.value = productData.results
  await loadOrders()
})

function goToNew() {
  router.push({ name: 'supplier-order-new' })
}

function goToDetail(order: SupplierOrder) {
  router.push({ name: 'supplier-order-detail', params: { id: order.id } })
}

function goToLedger(supplierId: number) {
  router.push({ name: 'supplier-ledger', params: { id: supplierId } })
}

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-slate-100 text-slate-600',
  CONFIRMED: 'bg-emerald-100 text-emerald-700',
  CANCELLED: 'bg-red-100 text-red-700',
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">Supplier Orders</h2>
      <button
        class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white"
        @click="goToNew"
      >
        New Order
      </button>
    </div>

    <div class="flex flex-wrap gap-3 rounded border bg-white p-3">
      <select
        v-model="filters.supplier"
        class="rounded border border-slate-300 px-2 py-1.5 text-sm"
        @change="loadOrders"
      >
        <option value="">All suppliers</option>
        <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name }}</option>
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
        <option value="CANCELLED">Cancelled</option>
      </select>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <div class="overflow-x-auto rounded border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-b text-slate-500">
            <th class="px-3 py-2 font-medium">Reference</th>
            <th class="px-3 py-2 font-medium">Supplier</th>
            <th class="px-3 py-2 font-medium">Product</th>
            <th class="px-3 py-2 font-medium text-right">Purchased (L)</th>
            <th class="px-3 py-2 font-medium text-right">Reliquat (L)</th>
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
            <td class="px-3 py-2 font-medium text-slate-800">{{ order.reference }}</td>
            <td class="px-3 py-2">
              <button
                class="text-slate-600 underline decoration-dotted hover:text-slate-900"
                @click.stop="goToLedger(order.supplier)"
              >
                {{ order.supplier_detail?.name }}
              </button>
            </td>
            <td class="px-3 py-2">{{ order.product_detail?.name }}</td>
            <td class="px-3 py-2 text-right">
              {{ Number(order.quantity_litres).toLocaleString() }}
            </td>
            <td
              class="px-3 py-2 text-right font-medium"
              :class="Number(order.reliquat) <= 0 ? 'text-red-600' : 'text-slate-800'"
            >
              {{ Number(order.reliquat).toLocaleString() }}
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
            <td colspan="6" class="px-3 py-6 text-center text-slate-400">
              No supplier orders yet.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
