import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import DeliveryNoteForm from '../DeliveryNoteForm.vue'
import LoadingSheetForm from '../LoadingSheetForm.vue'
import PurchaseOrderForm from '../PurchaseOrderForm.vue'

const replace = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: {} }),
  useRouter: () => ({ replace, push: vi.fn() }),
}))

const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results })
const create = vi.fn(async (payload: Record<string, unknown>) => ({
  id: 5,
  reference: 'X-1',
  ...payload,
}))
const lists: Record<string, () => unknown> = {
  '/customers/': () => page([{ id: 1, name: 'Baba Dembelé', address: 'Keneba' }]),
  '/suppliers/': () => page([{ id: 3, name: 'Vivo Energy' }]),
  '/trucks/': () =>
    page([
      {
        id: 11,
        internal_id: 'C1',
        tractor_registration: 'BA 2947 MD',
        tanker_registration: 'BA 1591 MD',
        capacity_litres: '45000.00',
      },
      {
        id: 12,
        internal_id: 'C2',
        tractor_registration: 'AA 033 FZ',
        tanker_registration: 'AA 205 FZ',
        capacity_litres: '45000.00',
      },
    ]),
  '/supplier-orders/': () =>
    page([
      {
        id: 8,
        reference: 'SO-1',
        supplier: 3,
        product: 2,
        product_detail: { id: 2, name: 'Gasoil' },
        quantity_litres: '180000.00',
        unit_price: '750.0000',
        currency: 'XOF',
      },
    ]),
  '/products/': () => page([{ id: 2, name: 'Gasoil', code: 'gasoil' }]),
}
let trucksFail = false
vi.mock('@/api/resource', () => ({
  createResourceApi: (path: string) => ({
    list: vi.fn(async () => {
      if (path === '/trucks/' && trucksFail) throw new Error('403')
      return lists[path] ? lists[path]() : page([])
    }),
    get: vi.fn(),
    create: (payload: Record<string, unknown>) => create(payload),
    update: vi.fn(),
    remove: vi.fn(),
  }),
}))

const fetchDeliverableTrips = vi.fn(async (_customer: number) => [
  {
    trip: 21,
    reference: 'TRIP-1',
    loading_date: '2026-10-01',
    truck: 'C1',
    designation: 'GASOIL',
    quantity: '44800.00',
    tanker: 'BP 8795 MD',
    tractor: 'AZ 7969 MD',
    missing: '200.00',
    other_notes: [],
  },
  {
    trip: 22,
    reference: 'TRIP-2',
    loading_date: '2026-10-02',
    truck: 'C2',
    designation: 'GASOIL',
    quantity: '45000.00',
    tanker: 'AA 473 AD',
    tractor: 'BN 6578 MD',
    missing: null,
    other_notes: ['BL-202610-0001'],
  },
])
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  fetchDeliverableTrips: (id: number) => fetchDeliverableTrips(id),
}))
vi.mock('@/modules/settings/api', () => ({
  fetchCompanyProfile: vi.fn(async () => ({ name: 'AZUR ÉNERGIE' })),
}))

describe('document forms', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    trucksFail = false
  })

  it('delivery note: picking delivered trips fills the lines', async () => {
    const wrapper = mount(DeliveryNoteForm)
    await flushPromises()
    await wrapper.find('[data-test="doc-customer"]').setValue('1')
    await flushPromises()
    expect(fetchDeliverableTrips).toHaveBeenCalledWith(1)
    expect((wrapper.find('#delivery_address').element as HTMLInputElement).value).toBe('Keneba')
    expect(wrapper.text()).toContain('Déjà sur BL-202610-0001')

    const boxes = wrapper.findAll('[data-test="trip-pick"]')
    await boxes[0]!.setValue(true)
    await boxes[1]!.setValue(true)
    expect(wrapper.findAll('[data-test="doc-line"]')).toHaveLength(2)
    expect((wrapper.find('[data-test="line-0-tractor"]').element as HTMLInputElement).value).toBe(
      'AZ 7969 MD',
    )

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const sent = create.mock.calls[0]![0]
    expect(sent.customer).toBe(1)
    expect((sent.lines as unknown[]).length).toBe(2)
    expect(replace).toHaveBeenCalledWith({ name: 'delivery-note-detail', params: { id: 5 } })
  })

  it('loading sheet: details first, then trucks with their capacity', async () => {
    const wrapper = mount(LoadingSheetForm)
    await flushPromises()
    expect((wrapper.find('#on_behalf_of').element as HTMLInputElement).value).toBe('AZUR ÉNERGIE')
    await wrapper.find('#supplier_name').setValue('Dépôt Moussala')
    await wrapper.find('#product_name').setValue('GASOIL')
    await wrapper.find('#route').setValue('MOUSSALA')
    await wrapper.find('[data-test="loading-next"]').trigger('click')

    const trucks = wrapper.findAll('[data-test="truck-pick"]')
    await trucks[0]!.setValue(true)
    await trucks[1]!.setValue(true)
    expect(
      (wrapper.find('[data-test="line-1-capacity_litres"]').element as HTMLInputElement).value,
    ).toBe('45000.00')
    expect((wrapper.find('[data-test="line-0-route"]').element as HTMLInputElement).value).toBe(
      'MOUSSALA',
    )
    expect(wrapper.find('[data-test="lines-total"]').text()).toContain('90')

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const sent = create.mock.calls[0]![0]
    expect(sent.supplier_name).toBe('Dépôt Moussala')
    expect((sent.lines as { truck: number }[]).map((l) => l.truck)).toEqual([11, 12])
  })

  it('purchase order: pre-fill from a supplier order and compute the total', async () => {
    const wrapper = mount(PurchaseOrderForm)
    await flushPromises()
    await wrapper.find('[data-test="po-prefill"]').setValue('8')
    await flushPromises()
    expect((wrapper.find('[data-test="po-supplier"]').element as HTMLSelectElement).value).toBe('3')
    expect((wrapper.find('[data-test="line-0-quantity"]').element as HTMLInputElement).value).toBe(
      '180000.00',
    )
    expect(wrapper.find('[data-test="po-total"]').text()).toContain('135')

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const sent = create.mock.calls[0]![0]
    expect(sent.supplier).toBe(3)
    expect(sent.supplier_order).toBe(8)
    expect(sent.lines).toEqual([
      {
        product: 2,
        description: 'Gasoil',
        quantity: '180000.00',
        unit: 'L',
        unit_price: '750.0000',
      },
    ])
  })

  it('loading sheet still works when the trucks cannot be loaded (no operations access)', async () => {
    trucksFail = true
    const wrapper = mount(LoadingSheetForm)
    await flushPromises()
    expect(wrapper.text()).not.toContain('Impossible de charger les documents.')
    expect(wrapper.findAll('select option').map((o) => o.text())).toContain('Vivo Energy')
  })
})
