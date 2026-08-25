<script setup lang="ts">
// Global search bar (docs/PHASE_6_PLAN.md Etape 8; guide Section 9.8):
// debounced GET /api/search/?q=, categorized results, trucks enriched with
// their current trip (status/product/volume/client).
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import { searchGlobal } from './api'
import type { SearchResults } from './types'

const { t, te } = useI18n()
const router = useRouter()

function statusLabel(namespace: string, status: string): string {
  const key = `${namespace}.${status}`
  return te(key) ? t(key) : status
}

const query = ref('')
const results = ref<SearchResults | null>(null)
const loading = ref(false)
let debounceHandle: ReturnType<typeof setTimeout> | undefined

function goTo(to: RouteLocationRaw) {
  router.push(to)
  query.value = ''
  results.value = null
}

const hasResults = computed(() => {
  if (!results.value) return false
  return Object.values(results.value).some((list) => list.length > 0)
})

watch(query, (value) => {
  if (debounceHandle) clearTimeout(debounceHandle)
  const trimmed = value.trim()
  if (!trimmed) {
    results.value = null
    return
  }
  debounceHandle = setTimeout(async () => {
    loading.value = true
    try {
      results.value = await searchGlobal(trimmed)
    } finally {
      loading.value = false
    }
  }, 300)
})
</script>

<template>
  <div class="relative w-72">
    <input
      v-model="query"
      type="search"
      :placeholder="t('search.placeholder')"
      class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-11 w-full rounded-lg border bg-white px-3.5 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
    />

    <div
      v-if="query.trim()"
      class="border-ligne absolute z-10 mt-1 max-h-96 w-full overflow-auto rounded-xl border bg-white shadow-lg"
    >
      <p v-if="loading" class="text-texte-3 px-3 py-2 text-sm">{{ t('search.searching') }}</p>
      <template v-else-if="results">
        <template v-if="results.trucks.length">
          <p class="text-texte-3 px-3 py-1 text-xs font-semibold">{{ t('search.trucks') }}</p>
          <button
            v-for="truck in results.trucks"
            :key="`truck-${truck.id}`"
            type="button"
            class="hover:bg-sable block w-full px-3 py-2 text-start text-sm"
            @click="goTo({ name: 'trucks' })"
          >
            <div class="text-texte font-medium">
              {{ truck.tractor_registration }} / {{ truck.tanker_registration }}
            </div>
            <div v-if="truck.current_trip" class="text-texte-2 text-xs">
              {{ statusLabel('trips.status', truck.current_trip.status) }} ·
              {{ truck.current_trip.reference }} · {{ truck.current_trip.product }} ·
              {{ Number(truck.current_trip.quantity_loaded).toLocaleString() }} L
              <span v-if="truck.current_trip.client"> · {{ truck.current_trip.client }}</span>
            </div>
            <div v-else class="text-texte-3 text-xs">{{ t('search.noActiveTrip') }}</div>
          </button>
        </template>

        <template v-if="results.customers.length">
          <p class="text-texte-3 px-3 py-1 text-xs font-semibold">{{ t('search.customers') }}</p>
          <button
            v-for="item in results.customers"
            :key="`customer-${item.id}`"
            type="button"
            class="hover:bg-sable block w-full px-3 py-2 text-start text-sm"
            @click="goTo({ name: 'customer-ledger', params: { id: item.id } })"
          >
            {{ item.name }}
          </button>
        </template>

        <template v-if="results.suppliers.length">
          <p class="text-texte-3 px-3 py-1 text-xs font-semibold">{{ t('search.suppliers') }}</p>
          <button
            v-for="item in results.suppliers"
            :key="`supplier-${item.id}`"
            type="button"
            class="hover:bg-sable block w-full px-3 py-2 text-start text-sm"
            @click="goTo({ name: 'supplier-ledger', params: { id: item.id } })"
          >
            {{ item.name }}
          </button>
        </template>

        <template v-if="results.transporters.length">
          <p class="text-texte-3 px-3 py-1 text-xs font-semibold">{{ t('search.transporters') }}</p>
          <button
            v-for="item in results.transporters"
            :key="`transporter-${item.id}`"
            type="button"
            class="hover:bg-sable block w-full px-3 py-2 text-start text-sm"
            @click="goTo({ name: 'transporter-ledger', params: { id: item.id } })"
          >
            {{ item.name }}
          </button>
        </template>

        <template v-if="results.trips.length">
          <p class="text-texte-3 px-3 py-1 text-xs font-semibold">{{ t('search.trips') }}</p>
          <button
            v-for="item in results.trips"
            :key="`trip-${item.id}`"
            type="button"
            class="hover:bg-sable block w-full px-3 py-2 text-start text-sm"
            @click="goTo({ name: 'trip-detail', params: { id: item.id } })"
          >
            {{ item.reference }} · {{ statusLabel('trips.status', item.status) }} ·
            {{ item.product }}
          </button>
        </template>

        <template v-if="results.invoices.length">
          <p class="text-texte-3 px-3 py-1 text-xs font-semibold">{{ t('search.invoices') }}</p>
          <button
            v-for="item in results.invoices"
            :key="`invoice-${item.id}`"
            type="button"
            class="hover:bg-sable block w-full px-3 py-2 text-start text-sm"
            @click="goTo({ name: 'invoice-detail', params: { id: item.id } })"
          >
            {{ item.invoice_number }} · {{ statusLabel('invoiceStatus', item.status) }}
          </button>
        </template>

        <template v-if="results.orders.length">
          <p class="text-texte-3 px-3 py-1 text-xs font-semibold">{{ t('search.orders') }}</p>
          <button
            v-for="item in results.orders"
            :key="`order-${item.id}`"
            type="button"
            class="hover:bg-sable block w-full px-3 py-2 text-start text-sm"
            @click="goTo({ name: 'customer-order-detail', params: { id: item.id } })"
          >
            #{{ item.id }} · {{ statusLabel('customerOrderStatus', item.status) }} ·
            {{ item.quantity_ordered }} L
          </button>
        </template>

        <template v-if="results.cessions.length">
          <p class="text-texte-3 px-3 py-1 text-xs font-semibold">{{ t('search.cessions') }}</p>
          <button
            v-for="item in results.cessions"
            :key="`cession-${item.id}`"
            type="button"
            class="hover:bg-sable block w-full px-3 py-2 text-start text-sm"
            @click="goTo({ name: 'cession-letter-detail', params: { id: item.id } })"
          >
            {{ item.reference }} · {{ statusLabel('cessionStatus', item.status) }}
          </button>
        </template>

        <p v-if="!hasResults" class="text-texte-3 px-3 py-2 text-sm">{{ t('search.noResults') }}</p>
      </template>
    </div>
  </div>
</template>
