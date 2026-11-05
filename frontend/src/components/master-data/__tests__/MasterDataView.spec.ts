import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import type { FieldSchema } from '@/components/master-data/types'
import { i18n } from '@/i18n'

// Bug fix (2026-09-18): destructive actions now go through the app's own
// popup instead of window.confirm() - see useConfirmDialog.
vi.mock('@/composables/useConfirmDialog', () => ({
  confirmDialog: vi.fn(async () => true),
}))

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

const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]

// Status actions live in the row's "⋯" menu (teleported to <body>).
async function clickRowAction(
  wrapper: { find: (s: string) => { trigger: (e: string) => Promise<void> } },
  label: string,
) {
  await wrapper.find('button[aria-label="Plus d\'actions"]').trigger('click')
  const item = Array.from(document.body.querySelectorAll('[role=menuitem]')).find(
    (el) => el.textContent?.trim() === label,
  ) as HTMLElement
  item.click()
}

function makeResource(initialRows: Record<string, unknown>[]) {
  const rows = [...initialRows]
  return {
    list: vi.fn(async () => ({ count: rows.length, next: null, previous: null, results: rows })),
    create: vi.fn(async (payload: Record<string, unknown>) => {
      const created = { id: rows.length + 1, ...payload }
      rows.push(created)
      return created
    }),
    update: vi.fn(async (id: number, payload: Record<string, unknown>) => {
      const index = rows.findIndex((r) => r.id === id)
      rows[index] = { ...rows[index], ...payload }
      return rows[index]
    }),
    remove: vi.fn(async (id: number) => {
      const index = rows.findIndex((r) => r.id === id)
      if (index !== -1) rows.splice(index, 1)
    }),
  }
}

describe('MasterDataView', () => {
  it('loads and renders rows on mount', async () => {
    const resource = makeResource([{ id: 1, name: 'Total Senegal', is_active: true }])
    const wrapper = mount(MasterDataView, {
      props: { title: 'Suppliers', resource, fields },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    expect(resource.list).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Total Senegal')
  })

  it('creates a new record through the Add flow', async () => {
    const resource = makeResource([])
    const wrapper = mount(MasterDataView, {
      props: { title: 'Suppliers', resource, fields },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Ajouter')!
      .trigger('click') // "Add" button
    await wrapper.find('input#name').setValue('Shell Mali')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(resource.create).toHaveBeenCalledWith(expect.objectContaining({ name: 'Shell Mali' }))
    expect(wrapper.text()).toContain('Shell Mali')
  })

  it('deletes a record through the Delete flow when there is no is_active field', async () => {
    const noActiveFields: FieldSchema[] = [
      { key: 'name', label: 'Name', type: 'text', required: true },
    ]
    const resource = makeResource([{ id: 1, name: 'Total Senegal' }])
    const wrapper = mount(MasterDataView, {
      props: { title: 'Suppliers', resource, fields: noActiveFields },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Total Senegal')

    const deleteButton = wrapper.findAll('button').find((b) => b.text() === 'Supprimer')
    await deleteButton!.trigger('click')
    await flushPromises()

    expect(resource.remove).toHaveBeenCalledWith(1)
    expect(wrapper.text()).not.toContain('Total Senegal')
  })

  it('toggles active status instead of deleting when an is_active field exists', async () => {
    const resource = makeResource([{ id: 1, name: 'Total Senegal', is_active: true }])
    const wrapper = mount(MasterDataView, {
      props: { title: 'Suppliers', resource, fields },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Total Senegal')
    expect(wrapper.findAll('button').find((b) => b.text() === 'Supprimer')).toBeUndefined()

    await clickRowAction(wrapper, 'Désactiver')
    await flushPromises()

    expect(resource.update).toHaveBeenCalledWith(1, { is_active: false })
    // Inactive records are hidden by default once toggled off.
    expect(wrapper.text()).not.toContain('Total Senegal')
  })

  it('loads every page of the API, not just the first 25 records', async () => {
    const page1 = Array.from({ length: 25 }, (_, i) => ({
      id: i + 1,
      name: `Row ${i + 1}`,
      is_active: false,
    }))
    const page2 = [{ id: 26, name: 'Row 26', is_active: true }]
    const resource = makeResource([])
    const listPages = vi.fn(async (params?: Record<string, unknown>) =>
      params?.page === 2
        ? { count: 26, next: null, previous: 'x', results: page2 }
        : { count: 26, next: 'page2', previous: null, results: page1 },
    )
    resource.list = listPages as unknown as typeof resource.list
    const wrapper = mount(MasterDataView, {
      props: { title: 'Trucks', resource, fields },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    expect(listPages).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('[role=tab]').map((b) => b.text())).toEqual([
      'Actifs (1)',
      'Inactifs (25)',
    ])
    expect(wrapper.text()).toContain('Row 26')
  })

  it('shows each group under its own Actifs / Inactifs button, with counts', async () => {
    const resource = makeResource([
      { id: 1, name: 'Total Senegal', is_active: true },
      { id: 2, name: 'Old Depot', is_active: false },
    ])
    const wrapper = mount(MasterDataView, {
      props: { title: 'Suppliers', resource, fields },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    const tab = (label: string) => wrapper.findAll('[role=tab]').find((b) => b.text() === label)
    expect(tab('Actifs (1)')).toBeDefined()
    expect(tab('Inactifs (1)')).toBeDefined()
    expect(tab('Anciens (0)')).toBeUndefined() // legacy only where legacy-support is set
    expect(wrapper.text()).toContain('Total Senegal')
    expect(wrapper.text()).not.toContain('Old Depot')

    await tab('Inactifs (1)')!.trigger('click')
    expect(wrapper.text()).toContain('Old Depot')
    expect(wrapper.text()).not.toContain('Total Senegal')

    await clickRowAction(wrapper, 'Activer')
    await flushPromises()

    expect(resource.update).toHaveBeenCalledWith(2, { is_active: true })
  })

  it('offers an Anciens group and moves a record there when legacy-support is set', async () => {
    const resource = makeResource([
      { id: 1, name: 'Total Senegal', is_active: true, is_legacy: false },
      { id: 2, name: 'Former Client', is_active: false, is_legacy: true },
      { id: 3, name: 'Settled Depot', is_active: false, is_legacy: false },
    ])
    const wrapper = mount(MasterDataView, {
      props: { title: 'Suppliers', resource, fields, legacySupport: true },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    const tab = (label: string) => wrapper.findAll('[role=tab]').find((b) => b.text() === label)
    expect(tab('Actifs (1)')).toBeDefined()
    expect(tab('Anciens (1)')).toBeDefined()
    expect(tab('Inactifs (1)')).toBeDefined()

    await tab('Anciens (1)')!.trigger('click')
    expect(wrapper.text()).toContain('Former Client')
    expect(wrapper.text()).not.toContain('Settled Depot')

    await tab('Actifs (1)')!.trigger('click')
    await clickRowAction(wrapper, 'Passer en ancien')
    await flushPromises()
    expect(resource.update).toHaveBeenCalledWith(1, { is_legacy: true, is_active: false })
  })

  it('shows the backend refusal when deactivating an account that still has a balance', async () => {
    const resource = makeResource([{ id: 1, name: 'Total Senegal', is_active: true }])
    resource.update = vi.fn(async () => {
      throw { response: { status: 400, data: { is_active: ['Solde non nul.'] } } }
    })
    const wrapper = mount(MasterDataView, {
      props: { title: 'Suppliers', resource, fields },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    await clickRowAction(wrapper, 'Désactiver')
    await flushPromises()

    expect(wrapper.text()).toContain('Solde non nul.')
  })

  it('surfaces the backend field error instead of a generic save message', async () => {
    // Phase 6 (docs/superpowers/specs/2026-09-02-business-corrections-6-
    // phases-design.md): e.g. TruckSerializer rejecting an EXTERNAL truck
    // with no owner_transporter - the message must reach the user, not
    // just a generic "save failed".
    const resource = makeResource([])
    resource.create = vi.fn(async () => {
      throw {
        response: {
          status: 400,
          data: { owner_transporter: ['Le transporteur est obligatoire pour un camion externe.'] },
        },
      }
    })
    const wrapper = mount(MasterDataView, {
      props: { title: 'Trucks', resource, fields },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Ajouter')!
      .trigger('click')
    await wrapper.find('input#name').setValue('TRK-EXT')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Le transporteur est obligatoire pour un camion externe.')
  })

  // UI recette fix (2026-09-05): a field's options can now depend on the
  // form's own live values (Truck's owner_transporter filtered by the
  // currently-selected ownership_type).
  it('recomputes form fields from the live form value via the formFields prop', async () => {
    const resource = makeResource([])
    const dependentFields: FieldSchema[] = [
      {
        key: 'kind',
        label: 'Kind',
        type: 'select',
        options: [
          { value: 'A', label: 'Kind A' },
          { value: 'B', label: 'Kind B' },
        ],
      },
      { key: 'detail', label: 'Detail', type: 'select', options: [] },
    ]
    function formFields(form: Record<string, unknown>): FieldSchema[] {
      const kind = (form.kind as string | undefined) ?? 'A'
      return dependentFields.map((field) =>
        field.key === 'detail'
          ? {
              ...field,
              options:
                kind === 'A'
                  ? [{ value: '1', label: 'Detail for A' }]
                  : [{ value: '2', label: 'Detail for B' }],
            }
          : field,
      )
    }
    const wrapper = mount(MasterDataView, {
      props: { title: 'Test', resource, fields: dependentFields, formFields },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Ajouter')!
      .trigger('click') // "Add"
    expect(wrapper.find('select#detail option').text()).toBe('Detail for A')

    await wrapper.find('select#kind').setValue('B')
    await flushPromises()

    expect(wrapper.find('select#detail option').text()).toBe('Detail for B')
  })

  it('renders a ledger link per row when ledgerRouteName is passed through', async () => {
    const resource = makeResource([{ id: 7, name: 'Total Senegal', is_active: true }])
    const wrapper = mount(MasterDataView, {
      props: { title: 'Suppliers', resource, fields, ledgerRouteName: 'customer-ledger' },
      global: { plugins: [i18n, makeRouter()] },
    })
    await flushPromises()

    const link = wrapper.find('a[href="/customers/7/ledger"]')
    expect(link.exists()).toBe(true)
  })
})
