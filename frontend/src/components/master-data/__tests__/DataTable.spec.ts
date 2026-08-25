import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import DataTable from '@/components/master-data/DataTable.vue'
import { i18n } from '@/i18n'

function makeRouter() {
  const stub = { template: '<div />' }
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/', name: 'home', component: stub },
      { path: '/customers/:id/ledger', name: 'customer-ledger', component: stub },
    ],
  })
}

describe('DataTable', () => {
  it('formats a phone column with a space between the dial code and the number', () => {
    const wrapper = mount(DataTable, {
      props: {
        columns: [{ key: 'phone', label: 'Téléphone', type: 'phone' }],
        rows: [{ id: 1, phone: '+22212340000' }],
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.text()).toContain('+222 12340000')
    expect(wrapper.text()).not.toContain('+22212340000')
  })

  it('does not render a ledger link when ledgerRouteName is not set', () => {
    const wrapper = mount(DataTable, {
      props: {
        columns: [{ key: 'name', label: 'Nom', type: 'text' }],
        rows: [{ id: 1, name: 'Client X' }],
      },
      global: { plugins: [i18n, makeRouter()] },
    })

    expect(wrapper.text()).not.toContain('Grand livre')
  })

  it('renders a ledger link pointing at the given route and row id when ledgerRouteName is set', () => {
    const wrapper = mount(DataTable, {
      props: {
        columns: [{ key: 'name', label: 'Nom', type: 'text' }],
        rows: [{ id: 42, name: 'Client X' }],
        ledgerRouteName: 'customer-ledger',
      },
      global: { plugins: [i18n, makeRouter()] },
    })

    const link = wrapper.find('a[href="/customers/42/ledger"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toBe('Grand livre')
  })
})
