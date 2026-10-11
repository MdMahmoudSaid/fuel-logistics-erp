<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import GlobalSearchBar from '@/modules/search/GlobalSearchBar.vue'
import AppLogo from '@/components/AppLogo.vue'
import Button from '@/components/ui/Button.vue'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import Icon, { type IconName } from '@/components/ui/Icon.vue'

interface NavItem {
  to: string
  labelKey: string
  module: string
}

// Icône associée à chaque route de nav (bottom bar mobile + feuille "Plus").
const NAV_ICONS: Record<string, IconName> = {
  home: 'chart-no-axes-combined',
  trips: 'route',
  'company-stock': 'package',
  suppliers: 'users',
  'supplier-orders': 'cart-plus',
  'cession-letters': 'file-signature',
  customers: 'users',
  'customer-orders': 'cart-plus',
  sales: 'trending-up',
  invoices: 'receipt-text',
  proformas: 'receipt',
  'delivery-notes': 'file-signature',
  'loading-sheets': 'truck',
  'purchase-orders': 'cart-plus',
  'company-settings': 'landmark',
  'treasury-transactions': 'wallet',
  'bank-accounts': 'landmark',
  'cash-accounts': 'banknote',
  profit: 'circle-dollar-sign',
  shareholders: 'pie-chart',
  transporters: 'truck',
  drivers: 'shield',
  trucks: 'truck',
  products: 'droplet',
  users: 'users',
  roles: 'shield-check',
  'loss-tolerance-settings': 'shield',
  reports: 'file-text',
  'audit-logs': 'file-text',
}
interface NavGroup {
  key: string
  titleKey: string
  items: NavItem[]
}

const HOME_ITEM: NavItem = { to: 'home', labelKey: 'navigation.home', module: 'reports' }

// Regroupement métier de la Sidebar (§ simplification nav) : chaque groupe
// est un accordéon repliable, seule l'entrée "Tableau de bord" reste un
// lien direct hors groupe.
const NAV_GROUPS: NavGroup[] = [
  {
    key: 'operations',
    titleKey: 'navigation.groups.operations',
    items: [
      { to: 'trips', labelKey: 'navigation.trips', module: 'operations' },
      { to: 'company-stock', labelKey: 'navigation.companyStock', module: 'operations' },
    ],
  },
  {
    key: 'purchasing',
    titleKey: 'navigation.groups.purchasing',
    items: [
      { to: 'suppliers', labelKey: 'navigation.suppliers', module: 'purchasing' },
      { to: 'supplier-orders', labelKey: 'navigation.supplierOrders', module: 'purchasing' },
      { to: 'cession-letters', labelKey: 'navigation.cessionLetters', module: 'purchasing' },
    ],
  },
  {
    key: 'sales',
    titleKey: 'navigation.groups.sales',
    items: [
      { to: 'customers', labelKey: 'navigation.customers', module: 'sales' },
      { to: 'customer-orders', labelKey: 'navigation.customerOrders', module: 'sales' },
      { to: 'sales', labelKey: 'navigation.sales', module: 'sales' },
      { to: 'invoices', labelKey: 'navigation.invoices', module: 'sales' },
    ],
  },
  {
    // Spec 2026-10-11 documents-commerciaux §1: printable documents only.
    key: 'documents',
    titleKey: 'navigation.groups.documents',
    items: [
      { to: 'proformas', labelKey: 'navigation.proformas', module: 'sales' },
      { to: 'delivery-notes', labelKey: 'navigation.deliveryNotes', module: 'sales' },
      { to: 'loading-sheets', labelKey: 'navigation.loadingSheets', module: 'purchasing' },
      { to: 'purchase-orders', labelKey: 'navigation.purchaseOrders', module: 'purchasing' },
    ],
  },
  {
    key: 'treasury',
    titleKey: 'navigation.groups.treasury',
    items: [
      {
        to: 'treasury-transactions',
        labelKey: 'navigation.treasuryTransactions',
        module: 'finance',
      },
      { to: 'expenses', labelKey: 'navigation.expenses', module: 'finance' },
      { to: 'bank-accounts', labelKey: 'navigation.bankAccounts', module: 'finance' },
      { to: 'cash-accounts', labelKey: 'navigation.cashAccounts', module: 'finance' },
    ],
  },
  {
    key: 'results',
    titleKey: 'navigation.groups.results',
    items: [
      { to: 'profit', labelKey: 'navigation.profit', module: 'shareholders' },
      { to: 'shareholders', labelKey: 'navigation.shareholders', module: 'shareholders' },
    ],
  },
  {
    key: 'logistics',
    titleKey: 'navigation.groups.logistics',
    items: [
      { to: 'transporters', labelKey: 'navigation.transporters', module: 'operations' },
      { to: 'drivers', labelKey: 'navigation.drivers', module: 'operations' },
      { to: 'trucks', labelKey: 'navigation.trucks', module: 'operations' },
    ],
  },
  {
    key: 'settings',
    titleKey: 'navigation.groups.settings',
    items: [
      { to: 'products', labelKey: 'navigation.products', module: 'operations' },
      { to: 'users', labelKey: 'navigation.users', module: 'admin' },
      { to: 'roles', labelKey: 'navigation.roles', module: 'admin' },
      { to: 'company-settings', labelKey: 'navigation.companySettings', module: 'admin' },
      {
        to: 'loss-tolerance-settings',
        labelKey: 'navigation.lossToleranceSettings',
        module: 'admin',
      },
      { to: 'reports', labelKey: 'navigation.reports', module: 'reports' },
      { to: 'audit-logs', labelKey: 'navigation.auditLogs', module: 'admin' },
    ],
  },
]

const NAV_ITEMS: NavItem[] = [HOME_ITEM, ...NAV_GROUPS.flatMap((group) => group.items)]

const { t } = useI18n()

// Sous-ensemble mis en avant dans la barre de navigation basse mobile
// (zone tactile 56px, §0.4) ; le reste reste accessible via "Plus".
const BOTTOM_NAV_KEYS = ['home', 'trips', 'sales', 'reports'] as const

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

// `home` lives at path '' under the parent '/', so its resolved path is
// '/' — vue-router's default (non-exact) active-class matching treats every
// other route's path as starting with '/' and highlights Dashboard on top
// of the real active item. Match on route name instead.
function isNavActive(name: string) {
  return route.name === name
}

const visibleNavItems = computed(() => NAV_ITEMS.filter((item) => auth.can(item.module, 'view')))
const homeVisible = computed(() => auth.can(HOME_ITEM.module, 'view'))

const bottomPrimaryItems = computed(() =>
  visibleNavItems.value.filter((item) => (BOTTOM_NAV_KEYS as readonly string[]).includes(item.to)),
)
const bottomOverflowItems = computed(() =>
  visibleNavItems.value.filter((item) => !(BOTTOM_NAV_KEYS as readonly string[]).includes(item.to)),
)

// Feuille "Plus" (mobile) groupée comme la sidebar desktop, moins les
// entrées déjà présentes dans la barre de navigation basse.
const overflowGroups = computed(() =>
  NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter(
      (item) =>
        auth.can(item.module, 'view') && !(BOTTOM_NAV_KEYS as readonly string[]).includes(item.to),
    ),
  })).filter((group) => group.items.length > 0),
)

const moreOpen = ref(false)

// Sidebar desktop groupée par domaine métier (accordéons repliables) — les
// groupes vides (aucune permission) disparaissent entièrement.
const visibleGroups = computed(() =>
  NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => auth.can(item.module, 'view')),
  })).filter((group) => group.items.length > 0),
)

const openGroups = reactive<Record<string, boolean>>(
  Object.fromEntries(
    NAV_GROUPS.map((group) => [group.key, group.items.some((item) => isNavActive(item.to))]),
  ),
)

function toggleGroup(key: string) {
  openGroups[key] = !openGroups[key]
}

// Garde le groupe de la route active déplié même après navigation, sans
// jamais refermer un groupe que l'utilisateur a ouvert manuellement.
watch(
  () => route.name,
  (name) => {
    const activeGroup = NAV_GROUPS.find((group) => group.items.some((item) => item.to === name))
    if (activeGroup) openGroups[activeGroup.key] = true
  },
)

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
    <aside
      class="bg-bitume sticky top-0 hidden h-screen w-60 shrink-0 flex-col overflow-y-auto md:flex"
    >
      <div class="px-4 py-4">
        <AppLogo tone="light" :size="28" />
      </div>
      <nav class="flex flex-col gap-0.5 px-2 pb-4">
        <RouterLink
          v-if="homeVisible"
          :to="{ name: HOME_ITEM.to }"
          class="text-sable/70 hover:bg-bitume-2 hover:text-sable flex h-11 items-center rounded-lg border-s-2 border-transparent px-3 text-sm transition"
          :class="
            isNavActive(HOME_ITEM.to) ? '!border-orange bg-bitume-2 !text-sable font-medium' : ''
          "
        >
          {{ t(HOME_ITEM.labelKey) }}
        </RouterLink>

        <div v-for="group in visibleGroups" :key="group.key" class="mt-1">
          <button
            type="button"
            class="text-sable/50 hover:text-sable/80 flex min-h-9 w-full items-center gap-2 rounded-lg px-3 py-1.5 text-start text-xs font-semibold tracking-wide uppercase transition"
            :aria-expanded="openGroups[group.key]"
            @click="toggleGroup(group.key)"
          >
            <span class="flex-1">{{ t(group.titleKey) }}</span>
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              class="shrink-0 transition-transform"
              :class="openGroups[group.key] ? 'rotate-180' : ''"
              aria-hidden="true"
            >
              <path
                d="M6 9l6 6 6-6"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </button>
          <div v-show="openGroups[group.key]" class="flex flex-col gap-0.5">
            <RouterLink
              v-for="item in group.items"
              :key="item.to"
              :to="{ name: item.to }"
              class="text-sable/70 hover:bg-bitume-2 hover:text-sable flex h-11 items-center rounded-lg border-s-2 border-transparent px-3 text-sm transition"
              :class="
                isNavActive(item.to) ? '!border-orange bg-bitume-2 !text-sable font-medium' : ''
              "
            >
              {{ t(item.labelKey) }}
            </RouterLink>
          </div>
        </div>
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
        {{ t('common.offline') }}
      </div>

      <header
        class="border-ligne flex h-16 shrink-0 items-center justify-between gap-2 border-b bg-white px-3 md:gap-4 md:px-6"
      >
        <div class="flex shrink-0 items-center gap-3 md:hidden">
          <AppLogo :wordmark="false" :size="28" />
        </div>
        <GlobalSearchBar
          v-if="auth.can('reports', 'view')"
          class="min-w-0 max-w-md flex-1 md:flex-none"
        />
        <span v-else class="text-texte-2 min-w-0 truncate text-sm">{{
          t('common.brandTagline')
        }}</span>
        <div class="flex shrink-0 items-center gap-2 md:gap-4">
          <span v-if="auth.user" class="text-texte-2 hidden text-sm sm:inline">
            {{ auth.user.full_name || auth.user.email }} · {{ auth.user.role_detail?.name }}
          </span>
          <div class="hidden sm:block">
            <LanguageSwitcher />
          </div>
          <Button
            variant="ghost"
            size="md"
            class="!h-11 !w-11 !px-0 text-sm sm:!h-9 sm:!w-auto sm:!px-3"
            :aria-label="t('header.logout')"
            :title="t('header.logout')"
            @click="onLogout"
          >
            <Icon name="log-out" :size="20" class="sm:hidden" />
            <span class="hidden sm:inline">{{ t('header.logout') }}</span>
          </Button>
        </div>
      </header>

      <main class="min-w-0 flex-1 p-4 pb-20 md:p-6 md:pb-6">
        <router-view />
      </main>
    </div>

    <!-- Bottom nav (mobile) — zone tactile 56px, §0.4 -->
    <nav
      data-test="mobile-bottom-nav"
      class="bg-bitume border-bitume-2 fixed inset-x-0 bottom-0 z-20 flex h-14 items-stretch border-t md:hidden"
      :aria-label="t('common.mainNavigation')"
    >
      <RouterLink
        v-for="item in bottomPrimaryItems"
        :key="item.to"
        :to="{ name: item.to }"
        class="text-sable/70 flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px]"
        :class="isNavActive(item.to) ? '!text-orange' : ''"
      >
        <Icon :name="NAV_ICONS[item.to] ?? 'route'" :size="20" />
        {{
          item.to === 'trips'
            ? t('navigation.tripsShort')
            : item.to === 'home'
              ? t('navigation.dashboardShort')
              : t(item.labelKey)
        }}
      </RouterLink>
      <button
        v-if="bottomOverflowItems.length"
        type="button"
        data-test="mobile-more-button"
        class="text-sable/70 flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px]"
        :class="moreOpen ? 'text-orange' : ''"
        @click="moreOpen = !moreOpen"
      >
        <Icon name="more-horizontal" :size="20" />
        {{ t('common.more') }}
      </button>
    </nav>

    <!-- Feuille "Plus" (mobile) -->
    <div
      v-if="moreOpen"
      data-test="mobile-more-sheet"
      class="fixed inset-0 z-30 flex items-end bg-black/40 md:hidden"
      @click.self="moreOpen = false"
    >
      <div class="bg-surface max-h-[70vh] w-full overflow-y-auto rounded-t-2xl p-4 pb-8">
        <div
          class="border-ligne-forte mx-auto mb-4 h-1.5 w-10 rounded-full border-0 bg-current opacity-20"
        />
        <div v-for="group in overflowGroups" :key="group.key" class="mb-3 last:mb-0">
          <p class="text-texte-3 px-3 pb-1 text-xs font-semibold tracking-wide uppercase">
            {{ t(group.titleKey) }}
          </p>
          <RouterLink
            v-for="item in group.items"
            :key="item.to"
            :to="{ name: item.to }"
            class="text-texte hover:bg-sable flex h-12 items-center gap-3 rounded-lg px-3 text-sm"
            @click="moreOpen = false"
          >
            <Icon :name="NAV_ICONS[item.to] ?? 'route'" :size="18" class="text-texte-2" />
            {{ t(item.labelKey) }}
          </RouterLink>
        </div>
        <div class="border-ligne mt-2 flex items-center justify-between border-t px-3 pt-3">
          <span class="text-texte-2 text-sm">{{ t('header.languageLabel') }}</span>
          <LanguageSwitcher />
        </div>
      </div>
    </div>
  </div>
</template>
