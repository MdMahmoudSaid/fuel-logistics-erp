<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const NAV_ITEMS = [
  { to: 'products', label: 'Products', module: 'operations' },
  { to: 'suppliers', label: 'Suppliers', module: 'purchasing' },
  { to: 'supplier-orders', label: 'Supplier Orders', module: 'purchasing' },
  { to: 'cession-letters', label: 'Cession Letters', module: 'purchasing' },
  { to: 'customers', label: 'Customers', module: 'sales' },
  { to: 'transporters', label: 'Transporters', module: 'operations' },
  { to: 'drivers', label: 'Drivers', module: 'operations' },
  { to: 'trucks', label: 'Trucks', module: 'operations' },
  { to: 'bank-accounts', label: 'Bank Accounts', module: 'finance' },
  { to: 'cash-accounts', label: 'Cash Accounts', module: 'finance' },
  { to: 'users', label: 'Users', module: 'admin' },
  { to: 'roles', label: 'Roles', module: 'admin' },
] as const

const auth = useAuthStore()
const router = useRouter()

const visibleNavItems = computed(() => NAV_ITEMS.filter((item) => auth.can(item.module, 'view')))

function onLogout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="flex min-h-screen bg-slate-50">
    <aside class="w-56 shrink-0 border-r bg-white">
      <div class="px-4 py-3 font-semibold text-slate-800">Fuel Logistics ERP</div>
      <nav class="flex flex-col gap-1 px-2">
        <RouterLink
          v-for="item in visibleNavItems"
          :key="item.to"
          :to="{ name: item.to }"
          class="rounded px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
          active-class="bg-slate-100 font-medium text-slate-900"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>

    <div class="flex-1">
      <header class="flex items-center justify-between border-b bg-white px-6 py-3 shadow-sm">
        <span class="text-sm text-slate-500">Fuel &amp; transport operations</span>
        <div class="flex items-center gap-4 text-sm text-slate-600">
          <span v-if="auth.user">
            {{ auth.user.full_name || auth.user.email }} · {{ auth.user.role_detail?.name }}
          </span>
          <button class="text-slate-500 hover:text-slate-800" @click="onLogout">Log out</button>
        </div>
      </header>
      <main class="p-6">
        <router-view />
      </main>
    </div>
  </div>
</template>
