<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { supplierOrderResource } from './api'
import type { SupplierOrder } from './types'
import type { SupplierBrief, ProductBrief } from './types'
import Badge from '@/components/ui/Badge.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import Button from '@/components/ui/Button.vue'

const router = useRouter()
const { t } = useI18n()

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
    error.value = t('purchasing.orderList.loadError')
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

function badgeVariant(status: string) {
  if (status === 'CONFIRMED') return 'livre' as const
  if (status === 'CANCELLED') return 'critique' as const
  return 'neutre' as const
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('purchasing.orderList.title') }}
      </h1>
      <Button variant="primary" @click="goToNew">{{ t('purchasing.orderList.newOrder') }}</Button>
    </div>

    <div class="flex flex-wrap gap-3">
      <select
        v-model="filters.supplier"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="loadOrders"
      >
        <option value="">{{ t('purchasing.orderList.allSuppliers') }}</option>
        <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <select
        v-model="filters.product"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="loadOrders"
      >
        <option value="">{{ t('purchasing.orderList.allProducts') }}</option>
        <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <select
        v-model="filters.status"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="loadOrders"
      >
        <option value="">{{ t('purchasing.orderList.allStatuses') }}</option>
        <option value="DRAFT">{{ t('supplierOrderStatus.DRAFT') }}</option>
        <option value="CONFIRMED">{{ t('supplierOrderStatus.CONFIRMED') }}</option>
        <option value="CANCELLED">{{ t('supplierOrderStatus.CANCELLED') }}</option>
      </select>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">{{ t('purchasing.orderList.table.reference') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('purchasing.orderList.table.supplier') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('purchasing.orderList.table.product') }}</th>
            <th class="px-3 py-2.5 text-right font-medium">
              {{ t('purchasing.orderList.table.purchased') }}
            </th>
            <th class="px-3 py-2.5 text-right font-medium">
              {{ t('purchasing.orderList.table.reliquat') }}
            </th>
            <th class="px-3 py-2.5 font-medium">{{ t('purchasing.orderList.table.status') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="order in orders"
            :key="order.id"
            class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
            @click="goToDetail(order)"
          >
            <td class="px-3 py-2.5"><MonoValue :value="order.reference" align="left" /></td>
            <td class="px-3 py-2.5">
              <button
                class="text-texte-2 hover:text-texte underline decoration-dotted"
                @click.stop="goToLedger(order.supplier)"
              >
                {{ order.supplier_detail?.name }}
              </button>
            </td>
            <td class="px-3 py-2.5">{{ order.product_detail?.name }}</td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="Number(order.quantity_litres).toLocaleString()" />
            </td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue
                :value="Number(order.reliquat).toLocaleString()"
                :class="Number(order.reliquat) <= 0 ? 'text-critique' : ''"
              />
            </td>
            <td class="px-3 py-2.5">
              <Badge :variant="badgeVariant(order.status)">{{
                t(`supplierOrderStatus.${order.status}`)
              }}</Badge>
            </td>
          </tr>
          <tr v-if="!loading && orders.length === 0">
            <td colspan="6" class="text-texte-3 px-3 py-8 text-center">
              {{ t('purchasing.orderList.noOrders') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
