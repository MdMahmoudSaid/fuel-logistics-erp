import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import TruckView from '../TruckView.vue'
import { i18n } from '@/i18n'

const transporters = [
  { id: 1, name: 'Flotte propre / Interne', is_internal: true },
  { id: 2, name: 'Flotte Nord', is_internal: true },
  { id: 3, name: 'Diallo Transport', is_internal: false },
]
const drivers = [{ id: 10, name: 'Ibrahim Kone' }]

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

const truckList = vi.fn(async () => paginated([]))
const truckCreate = vi.fn(async (payload: Record<string, unknown>) => ({ id: 99, ...payload }))
const driverCreate = vi.fn(async (payload: Record<string, unknown>) => ({
  id: 20,
  name: payload.name,
  phone: payload.phone ?? '',
}))
const transporterList = vi.fn(async () => paginated(transporters))

vi.mock('@/api/resource', () => ({
  createResourceApi: (path: string) => {
    if (path === '/trucks/') {
      return { list: truckList, create: truckCreate, update: vi.fn(), remove: vi.fn() }
    }
    if (path === '/transporters/') {
      return { list: transporterList }
    }
    if (path === '/drivers/') {
      return { list: vi.fn(async () => paginated(drivers)), create: driverCreate }
    }
    throw new Error(`unexpected resource path in test: ${path}`)
  },
}))

async function mountAndOpenCreate() {
  const wrapper = mount(TruckView, { global: { plugins: [i18n] } })
  await flushPromises()
  await wrapper.find('button').trigger('click') // "Ajouter"
  await flushPromises()
  return wrapper
}

describe('TruckView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // UI recette fix (2026-09-05): owner_transporter must only ever list
  // transporters compatible with the truck's own ownership_type.
  it('lists only internal transporters when ownership is Propriete de l\'entreprise (the default)', async () => {
    const wrapper = await mountAndOpenCreate()

    const options = wrapper.findAll('select#owner_transporter option').map((o) => o.text())
    expect(options).toEqual(['Flotte propre / Interne', 'Flotte Nord'])
    expect(options).not.toContain('Diallo Transport')
  })

  it('lists only external transporters after switching ownership to Externe / loue', async () => {
    const wrapper = await mountAndOpenCreate()

    await wrapper.find('select#ownership_type').setValue('EXTERNAL')
    await flushPromises()

    const options = wrapper.findAll('select#owner_transporter option').map((o) => o.text())
    expect(options).toEqual(['Diallo Transport'])
  })

  it('shows a clear message instead of "Aucun" when no external transporter exists', async () => {
    transporterList.mockResolvedValueOnce(
      paginated([{ id: 1, name: 'Flotte propre / Interne', is_internal: true }]),
    )
    const wrapper = await mountAndOpenCreate()

    await wrapper.find('select#ownership_type').setValue('EXTERNAL')
    await flushPromises()

    const options = wrapper.findAll('select#owner_transporter option').map((o) => o.text())
    expect(options).toEqual([
      "Aucun transporteur externe disponible. Créez d'abord un transporteur externe.",
    ])
  })

  it('creates a driver from the truck form, selects it, and keeps other field values', async () => {
    const wrapper = await mountAndOpenCreate()

    await wrapper.find('input#tractor_registration').setValue('AA-111-SN')
    await wrapper.find('[data-test="quick-create-toggle-default_driver"]').trigger('click')
    await wrapper.find('#default_driver_name').setValue('Ibrahim Kone')
    await wrapper.find('[data-test="quick-create-submit-default_driver"]').trigger('click')
    await flushPromises()

    expect(driverCreate).toHaveBeenCalledWith({ name: 'Ibrahim Kone' })
    expect((wrapper.find('select#default_driver').element as HTMLSelectElement).value).toBe('20')
    expect((wrapper.find('input#tractor_registration').element as HTMLInputElement).value).toBe(
      'AA-111-SN',
    )

    // The newly created driver is also immediately available in the
    // dropdown's option list (not just pre-selected as a stray value).
    const driverOptions = wrapper.findAll('select#default_driver option').map((o) => o.text())
    expect(driverOptions).toContain('Ibrahim Kone')

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(truckCreate).toHaveBeenCalledWith(
      expect.objectContaining({ tractor_registration: 'AA-111-SN', default_driver: '20' }),
    )
  })
})
