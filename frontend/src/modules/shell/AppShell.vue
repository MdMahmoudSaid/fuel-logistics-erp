<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import GlobalSearchBar from '@/modules/search/GlobalSearchBar.vue'
import AppLogo from '@/components/AppLogo.vue'
import Button from '@/components/ui/Button.vue'

const NAV_ITEMS = [
  { to: 'home', label: 'Dashboard', module: 'reports' },
  { to: 'products', label: 'Products', module: 'operations' },
  { to: 'suppliers', label: 'Suppliers', module: 'purchasing' },
  { to: 'supplier-orders', label: 'Supplier Orders', module: 'purchasing' },
  { to: 'cession-letters', label: 'Cession Letters', module: 'purchasing' },
  { to: 'customers', label: 'Customers', module: 'sales' },
  { to: 'customer-orders', label: 'Customer Orders', module: 'sales' },
  { to: 'trips', label: 'Trips & Loading', module: 'operations' },
  { to: 'sales', label: 'Sales', module: 'sales' },
  { to: 'invoices', label: 'Invoices', module: 'sales' },
  { to: 'transporters', label: 'Transporters', module: 'operations' },
  { to: 'drivers', label: 'Drivers', module: 'operations' },
  { to: 'trucks', label: 'Trucks', module: 'operations' },
  { to: 'bank-accounts', label: 'Bank Accounts', module: 'finance' },
  { to: 'cash-accounts', label: 'Cash Accounts', module: 'finance' },
  { to: 'customer-payment-new', label: 'Record Customer Payment', module: 'finance' },
  { to: 'expense-new', label: 'Record Expense', module: 'finance' },
  { to: 'treasury-transactions', label: 'Treasury Journal', module: 'finance' },
  { to: 'treasury-transfer', label: 'Internal Transfer', module: 'finance' },
  { to: 'reports', label: 'Reports', module: 'reports' },
  { to: 'users', label: 'Users', module: 'admin' },
  { to: 'roles', label: 'Roles', module: 'admin' },
  { to: 'loss-tolerance-settings', label: 'Loss Tolerance', module: 'admin' },
  { to: 'audit-logs', label: 'Audit Log', module: 'admin' },
] as const

// Sous-ensemble mis en avant dans la barre de navigation basse mobile
// (zone tactile 56px, §0.4) ; le reste reste accessible via "Plus".
const BOTTOM_NAV_KEYS = ['home', 'trips', 'sales', 'reports'] as const

const auth = useAuthStore()
const router = useRouter()

const visibleNavItems = computed(() => NAV_ITEMS.filter((item) => auth.can(item.module, 'view')))

const bottomPrimaryItems = computed(() =>
  visibleNavItems.value.filter((item) => (BOTTOM_NAV_KEYS as readonly string[]).includes(item.to)),
)
const bottomOverflowItems = computed(() =>
  visibleNavItems.value.filter((item) => !(BOTTOM_NAV_KEYS as readonly string[]).includes(item.to)),
)

const moreOpen = ref(false)

function onLogout() {
  auth.logout()
  router.push({ name: 'login' })
}

const isOnline = ref(navigator.onLine)
function updateOnlineStatus() {
  isOnline.value = navigator.onLine
}
onMounted(() => {
  window.addEventListener('online', updateOnlineStatus)
  window.addEventListener('offline', updateOnlineStatus)
})
onUnmounted(() => {
  window.removeEventListener('online', updateOnlineStatus)
  window.removeEventListener('offline', updateOnlineStatus)
})
</script>

<template>
  <div class="bg-sable text-texte flex min-h-screen">
    <!-- Sidebar (desktop) -->
    <aside class="bg-bitume hidden w-60 shrink-0 flex-col md:flex">
      <div class="px-4 py-4">
        <AppLogo tone="light" :size="28" />
      </div>
      <nav class="flex flex-col gap-0.5 px-2">
        <RouterLink
          v-for="item in visibleNavItems"
          :key="item.to"
          :to="{ name: item.to }"
          class="text-sable/70 hover:bg-bitume-2 hover:text-sable flex h-11 items-center rounded-lg border-l-2 border-transparent px-3 text-sm transition"
          active-class="!border-orange bg-bitume-2 !text-sable font-medium"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <!-- Alerte Hors Ligne — §4 -->
      <div
        v-if="!isOnline"
        class="bg-ecart-tint text-ecart-texte flex h-9 items-center justify-center gap-2 px-4 text-sm font-medium"
        role="status"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M3 3l18 18M8.5 8.7A9.9 9.9 0 0 1 12 8c3.5 0 6.6 1.4 8.9 3.7M5.1 11.7A9.9 9.9 0 0 1 8.4 9.6M2 8.8a13.9 13.9 0 0 1 3-2.2M12 16a2 2 0 0 1 1.8 1.1M12 16a2 2 0 0 0-1.4.6"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        Hors ligne — les modifications seront synchronisées au retour du réseau.
      </div>

      <header
        class="border-ligne flex h-16 shrink-0 items-center justify-between border-b bg-white px-4 md:px-6"
      >
        <div class="flex items-center gap-3 md:hidden">
          <AppLogo :wordmark="false" :size="28" />
        </div>
        <GlobalSearchBar v-if="auth.can('reports', 'view')" class="max-w-md flex-1 md:flex-none" />
        <span v-else class="text-texte-2 text-sm">Fuel &amp; transport operations</span>
        <div class="flex items-center gap-4">
          <span v-if="auth.user" class="text-texte-2 hidden text-sm sm:inline">
            {{ auth.user.full_name || auth.user.email }} · {{ auth.user.role_detail?.name }}
          </span>
          <Button variant="ghost" size="md" class="!h-9 !px-3 text-sm" @click="onLogout"
            >Log out</Button
          >
        </div>
      </header>

      <main class="min-w-0 flex-1 p-4 pb-20 md:p-6 md:pb-6">
        <router-view />
      </main>
    </div>

    <!-- Bottom nav (mobile) — zone tactile 56px, §0.4 -->
    <nav
      class="bg-bitume border-bitume-2 fixed inset-x-0 bottom-0 z-20 flex h-14 items-stretch border-t md:hidden"
      aria-label="Navigation principale"
    >
      <RouterLink
        v-for="item in bottomPrimaryItems"
        :key="item.to"
        :to="{ name: item.to }"
        class="text-sable/70 flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px]"
        active-class="!text-orange"
      >
        {{ item.label }}
      </RouterLink>
      <button
        v-if="bottomOverflowItems.length"
        type="button"
        class="text-sable/70 flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px]"
        :class="moreOpen ? 'text-orange' : ''"
        @click="moreOpen = !moreOpen"
      >
        Plus
      </button>
    </nav>

    <!-- Feuille "Plus" (mobile) -->
    <div
      v-if="moreOpen"
      class="fixed inset-0 z-30 flex items-end bg-black/40 md:hidden"
      @click.self="moreOpen = false"
    >
      <div class="bg-surface max-h-[70vh] w-full overflow-y-auto rounded-t-2xl p-4 pb-8">
        <div
          class="border-ligne-forte mx-auto mb-4 h-1.5 w-10 rounded-full border-0 bg-current opacity-20"
        />
        <RouterLink
          v-for="item in bottomOverflowItems"
          :key="item.to"
          :to="{ name: item.to }"
          class="text-texte hover:bg-sable flex h-12 items-center rounded-lg px-3 text-sm"
          @click="moreOpen = false"
        >
          {{ item.label }}
        </RouterLink>
      </div>
    </div>
  </div>
</template>
