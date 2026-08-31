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
      { path: '/transporters', name: 'transporters', component: stub },
      { path: '/drivers', name: 'drivers', component: stub },
      { path: '/trucks', name: 'trucks', component: stub },
      { path: '/bank-accounts', name: 'bank-accounts', component: stub },
      { path: '/cash-accounts', name: 'cash-accounts', component: stub },
      { path: '/treasury/transactions', name: 'treasury-transactions', component: stub },
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
