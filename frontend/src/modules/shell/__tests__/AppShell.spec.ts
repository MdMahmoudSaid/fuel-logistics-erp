import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import AppShell from '@/modules/shell/AppShell.vue'
import { useAuthStore } from '@/stores/auth'
import { i18n } from '@/i18n'

function makeRouter() {
  const stub = { template: '<div />' }
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/', name: 'home', component: stub },
      { path: '/products', name: 'products', component: stub },
      { path: '/suppliers', name: 'suppliers', component: stub },
      { path: '/supplier-orders', name: 'supplier-orders', component: stub },
      { path: '/cession-letters', name: 'cession-letters', component: stub },
      { path: '/customers', name: 'customers', component: stub },
      { path: '/customer-orders', name: 'customer-orders', component: stub },
      { path: '/trips', name: 'trips', component: stub },
      { path: '/company-stock', name: 'company-stock', component: stub },
      { path: '/loss-report', name: 'loss-report', component: stub },
      { path: '/sales', name: 'sales', component: stub },
      { path: '/invoices', name: 'invoices', component: stub },
      { path: '/proformas', name: 'proformas', component: stub },
      { path: '/delivery-notes', name: 'delivery-notes', component: stub },
      { path: '/loading-sheets', name: 'loading-sheets', component: stub },
      { path: '/purchase-orders', name: 'purchase-orders', component: stub },
      { path: '/company-settings', name: 'company-settings', component: stub },
      { path: '/transporters', name: 'transporters', component: stub },
      { path: '/drivers', name: 'drivers', component: stub },
      { path: '/trucks', name: 'trucks', component: stub },
      { path: '/bank-accounts', name: 'bank-accounts', component: stub },
      { path: '/cash-accounts', name: 'cash-accounts', component: stub },
      { path: '/treasury/transactions', name: 'treasury-transactions', component: stub },
      { path: '/expenses', name: 'expenses', component: stub },
      { path: '/shareholders', name: 'shareholders', component: stub },
      { path: '/profit', name: 'profit', component: stub },
      { path: '/reports', name: 'reports', component: stub },
      { path: '/audit-logs', name: 'audit-logs', component: stub },
      { path: '/settings/loss-tolerance', name: 'loss-tolerance-settings', component: stub },
      { path: '/users', name: 'users', component: stub },
      { path: '/roles', name: 'roles', component: stub },
    ],
  })
}

describe('AppShell navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('only shows nav items the user role can view', async () => {
    const router = makeRouter()
    await router.push('/')
    await router.isReady()

    const auth = useAuthStore()
    auth.user = {
      id: 1,
      phone: '+22212345678',
      email: 'ops@example.com',
      full_name: 'Ops User',
      role: 3,
      role_detail: { id: 3, name: 'Operations', permissions: { operations: ['view'] } },
    }

    const wrapper = mount(AppShell, { global: { plugins: [router, i18n] } })

    expect(wrapper.text()).toContain('Produits')
    expect(wrapper.text()).not.toContain('Utilisateurs')
  })

  it('keeps the desktop sidebar sticky and independently scrollable', async () => {
    const router = makeRouter()
    await router.push('/')
    await router.isReady()

    const auth = useAuthStore()
    auth.user = {
      id: 1,
      phone: '+22212345678',
      email: 'admin@example.com',
      full_name: 'Admin User',
      role: 1,
      role_detail: {
        id: 1,
        name: 'Admin',
        permissions: {
          reports: ['view'],
          operations: ['view'],
          purchasing: ['view'],
          sales: ['view'],
          finance: ['view'],
          shareholders: ['view'],
          admin: ['view'],
        },
      },
    }

    const wrapper = mount(AppShell, { global: { plugins: [router, i18n] } })
    const sidebar = wrapper.find('aside')

    expect(sidebar.classes()).toContain('sticky')
    expect(sidebar.classes()).toContain('top-0')
    expect(sidebar.classes()).toContain('h-screen')
    expect(sidebar.classes()).toContain('overflow-y-auto')
  })
})

// Phase "UI responsive mobile" (WIP groupe C): bottom nav bar + feuille
// "Plus" — couverture minimale demandée avant commit séparé.
describe('AppShell mobile navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function mountAsAdmin(router = makeRouter()) {
    const auth = useAuthStore()
    auth.user = {
      id: 1,
      phone: '+22212345678',
      email: 'admin@example.com',
      full_name: 'Admin User',
      role: 1,
      role_detail: {
        id: 1,
        name: 'Admin',
        permissions: {
          reports: ['view'],
          operations: ['view'],
          purchasing: ['view'],
          sales: ['view'],
          finance: ['view'],
          shareholders: ['view'],
          admin: ['view'],
        },
      },
    }
    return mount(AppShell, { global: { plugins: [router, i18n] } })
  }

  it('shows the bottom nav bar with the primary items, hidden above the mobile breakpoint', async () => {
    const router = makeRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mountAsAdmin(router)

    const bottomNav = wrapper.find('[data-test="mobile-bottom-nav"]')
    expect(bottomNav.exists()).toBe(true)
    expect(bottomNav.classes()).toContain('md:hidden')
    expect(bottomNav.text()).toContain('Accueil')
    expect(bottomNav.text()).toContain('Trajets')
    expect(bottomNav.text()).toContain('Ventes')
    expect(bottomNav.text()).toContain('Rapports')
  })

  it('only shows bottom nav items the role has permission to view', async () => {
    const router = makeRouter()
    await router.push('/')
    await router.isReady()
    const auth = useAuthStore()
    auth.user = {
      id: 2,
      phone: '+22212345679',
      email: 'ops@example.com',
      full_name: 'Ops User',
      role: 3,
      role_detail: {
        id: 3,
        name: 'Operations',
        // No "sales" permission -> the "Ventes" bottom-nav entry must not render.
        permissions: { operations: ['view'], reports: ['view'] },
      },
    }
    const wrapper = mount(AppShell, { global: { plugins: [router, i18n] } })

    const bottomNav = wrapper.find('[data-test="mobile-bottom-nav"]')
    expect(bottomNav.text()).toContain('Trajets')
    expect(bottomNav.text()).toContain('Rapports')
    expect(bottomNav.text()).not.toContain('Ventes')
  })

  it('opens and closes the "Plus" sheet from the bottom nav button', async () => {
    const router = makeRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mountAsAdmin(router)

    expect(wrapper.find('[data-test="mobile-more-sheet"]').exists()).toBe(false)

    await wrapper.find('[data-test="mobile-more-button"]').trigger('click')
    expect(wrapper.find('[data-test="mobile-more-sheet"]').exists()).toBe(true)

    await wrapper.find('[data-test="mobile-more-button"]').trigger('click')
    expect(wrapper.find('[data-test="mobile-more-sheet"]').exists()).toBe(false)
  })

  it('closes the "Plus" sheet when a nav item inside it is clicked', async () => {
    const router = makeRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mountAsAdmin(router)

    await wrapper.find('[data-test="mobile-more-button"]').trigger('click')
    const sheet = wrapper.find('[data-test="mobile-more-sheet"]')
    expect(sheet.exists()).toBe(true)

    const firstItem = sheet.find('a')
    expect(firstItem.exists()).toBe(true)
    await firstItem.trigger('click')

    expect(wrapper.find('[data-test="mobile-more-sheet"]').exists()).toBe(false)
  })
})
