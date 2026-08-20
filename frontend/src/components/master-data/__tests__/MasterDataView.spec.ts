import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import type { FieldSchema } from '@/components/master-data/types'
import { i18n } from '@/i18n'

const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]

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

    await wrapper.find('button').trigger('click') // "Add" button
    await wrapper.find('input#name').setValue('Shell Mali')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(resource.create).toHaveBeenCalledWith(expect.objectContaining({ name: 'Shell Mali' }))
    expect(wrapper.text()).toContain('Shell Mali')
  })

  it('deletes a record through the Delete flow', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const resource = makeResource([{ id: 1, name: 'Total Senegal', is_active: true }])
    const wrapper = mount(MasterDataView, {
      props: { title: 'Suppliers', resource, fields },
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
})
