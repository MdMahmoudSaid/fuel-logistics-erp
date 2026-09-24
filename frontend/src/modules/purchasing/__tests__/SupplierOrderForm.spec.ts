import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import SupplierOrderForm from '../SupplierOrderForm.vue'

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

vi.mock('@/api/resource', () => ({
  createResourceApi: vi.fn(() => ({
    list: vi.fn(async () => paginated([])),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  })),
}))

const create = vi.fn()
const getOrder = vi.fn()
const updateOrder = vi.fn()
const uploadDocument = vi.fn()
const fetchNextSupplierOrderReference = vi.fn(async () => 'ACH-202608-0007')
vi.mock('../api', () => ({
  supplierOrderResource: {
    get: (id: number) => getOrder(id),
    create: (payload: Record<string, unknown>) => create(payload),
    update: (id: number, payload: Record<string, unknown>) => updateOrder(id, payload),
  },
  uploadDocument: (payload: Record<string, unknown>) => uploadDocument(payload),
  fetchNextSupplierOrderReference: () => fetchNextSupplierOrderReference(),
}))

function makeRouter() {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/supplier-orders/new', name: 'supplier-order-new', component: SupplierOrderForm },
      { path: '/supplier-orders/:id', name: 'supplier-order-detail', component: stub },
      { path: '/supplier-orders', name: 'supplier-orders', component: stub },
    ],
  })
  router.push({ name: 'supplier-order-new' })
  return router
}

function makeEditRouter() {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/supplier-orders/:id', name: 'supplier-order-detail', component: SupplierOrderForm },
      { path: '/supplier-orders/new', name: 'supplier-order-new', component: stub },
      { path: '/supplier-orders', name: 'supplier-orders', component: stub },
    ],
  })
  router.push({ name: 'supplier-order-detail', params: { id: '7' } })
  return router
}

function confirmedOrder(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    reference: 'ACH-202609-0001',
    supplier: 1,
    product: 1,
    purchase_date: '2026-09-15',
    quantity_litres: '500000.00',
    unit_price: '740.0000',
    currency: 'XOF',
    total_amount: '370000000.00',
    optional_costs: null,
    notes: '',
    status: 'CONFIRMED',
    reliquat: '0.00',
    loaded_quantity: '500000.00',
    documents: [],
    cessions: [],
    ...overrides,
  }
}

describe('SupplierOrderForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('pre-fills the reference as a read-only, server-generated value', async () => {
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(SupplierOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    const input = wrapper.find<HTMLInputElement>('#reference')
    expect(input.attributes('autocomplete')).toBe('off')
    expect(input.attributes('disabled')).toBeDefined()
    expect(input.element.value).toBe('ACH-202608-0007')
    expect(fetchNextSupplierOrderReference).toHaveBeenCalled()
  })

  it('surfaces a backend uniqueness error under the reference field instead of a generic message', async () => {
    create.mockRejectedValueOnce({
      response: { status: 400, data: { reference: ['Cette référence existe déjà.'] } },
    })
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(SupplierOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#supplier').setValue('')
    await wrapper.find('#purchase_date').setValue('2026-08-20')
    await wrapper.find('#quantity_litres').setValue('1000')
    await wrapper.find('#unit_price').setValue('600')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Cette référence existe déjà.')
    expect(wrapper.text()).not.toContain("Impossible d'enregistrer")
  })

  it('shows creation documents and live calculated totals before first save', async () => {
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(SupplierOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Justificatifs')
    expect(wrapper.text()).not.toContain('Lettres de cession')

    await wrapper.find('#quantity_litres').setValue('100000')
    await wrapper.find('#unit_price').setValue('500')

    expect(wrapper.text()).toContain('50 000 000 XOF')
    expect(wrapper.text()).toContain('100 000 L')
  })

  it('uploads every selected image automatically after creating the supplier order', async () => {
    create.mockResolvedValueOnce({ id: 77 })
    uploadDocument.mockResolvedValue(undefined)
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(SupplierOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    const input = wrapper.find<HTMLInputElement>('input[type="file"]')
    const files = [
      new File(['png'], 'contrat.png', { type: 'image/png' }),
      new File(['jpg'], 'recu.jpg', { type: 'image/jpeg' }),
    ]
    Object.defineProperty(input.element, 'files', { value: files, configurable: true })
    await input.trigger('change')

    await wrapper.find('#supplier').setValue('1')
    await wrapper.find('#product').setValue('1')
    await wrapper.find('#purchase_date').setValue('2026-08-20')
    await wrapper.find('#quantity_litres').setValue('100000')
    await wrapper.find('#unit_price').setValue('500')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(create).toHaveBeenCalled()
    expect(uploadDocument).toHaveBeenCalledTimes(2)
    expect(uploadDocument).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ file: files[0], contentTypeName: 'supplierorder', objectId: 77 }),
    )
    expect(uploadDocument).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ file: files[1], contentTypeName: 'supplierorder', objectId: 77 }),
    )
    expect(router.currentRoute.value.name).toBe('supplier-order-detail')
    expect(router.currentRoute.value.params.id).toBe('77')
  })

  it('keeps the created order accessible and shows a clear message when a post-create upload fails', async () => {
    create.mockResolvedValueOnce({ id: 88 })
    uploadDocument.mockRejectedValueOnce(new Error('upload failed'))
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(SupplierOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    const input = wrapper.find<HTMLInputElement>('input[type="file"]')
    const file = new File(['png'], 'contrat.png', { type: 'image/png' })
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')

    await wrapper.find('#supplier').setValue('1')
    await wrapper.find('#product').setValue('1')
    await wrapper.find('#purchase_date').setValue('2026-08-20')
    await wrapper.find('#quantity_litres').setValue('100000')
    await wrapper.find('#unit_price').setValue('500')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Commande créée, mais certains documents')
    expect(router.currentRoute.value.name).toBe('supplier-order-detail')
    expect(router.currentRoute.value.params.id).toBe('88')
  })

  it('rejects a non-image file before uploading it', async () => {
    const router = makeRouter()
    await router.isReady()
    const wrapper = mount(SupplierOrderForm, { global: { plugins: [router] } })
    await flushPromises()

    const input = wrapper.find<HTMLInputElement>('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['pdf'], 'contrat.pdf', { type: 'application/pdf' })],
      configurable: true,
    })
    await input.trigger('change')

    expect(wrapper.text()).toContain('Seules les images JPG, JPEG, PNG ou WEBP sont autorisées.')
    expect(uploadDocument).not.toHaveBeenCalled()
  })

  describe('amending a confirmed order', () => {
    async function mountEdit(order = confirmedOrder()) {
      getOrder.mockResolvedValue(order)
      updateOrder.mockResolvedValue(order)
      const router = makeEditRouter()
      await router.isReady()
      const wrapper = mount(SupplierOrderForm, { global: { plugins: [router] } })
      await flushPromises()
      return wrapper
    }

    it('does not ask for a reason until a financial field is changed', async () => {
      const wrapper = await mountEdit()
      expect(wrapper.find('#amend_reason').exists()).toBe(false)
    })

    it('shows the minimum quantity notice when litres are already loaded', async () => {
      const wrapper = await mountEdit()
      expect(wrapper.text()).toContain('500 000')
      expect(wrapper.find('[data-testid="amend-minimum-notice"]').exists()).toBe(true)
    })

    it('hides the minimum notice when nothing is loaded', async () => {
      const wrapper = await mountEdit(confirmedOrder({ loaded_quantity: '0.00' }))
      expect(wrapper.find('[data-testid="amend-minimum-notice"]').exists()).toBe(false)
    })

    it('requires a reason once quantity is edited and sends it with the update', async () => {
      const wrapper = await mountEdit()
      await wrapper.find('#quantity_litres').setValue('720000')

      const reason = wrapper.find<HTMLTextAreaElement>('#amend_reason')
      expect(reason.exists()).toBe(true)
      expect(reason.attributes('required')).toBeDefined()

      await reason.setValue('Erreur de saisie sur la quantité')
      await wrapper.find('form').trigger('submit.prevent')
      await flushPromises()

      expect(updateOrder).toHaveBeenCalledTimes(1)
      const payload = updateOrder.mock.calls[0]![1]
      expect(Number(payload.quantity_litres)).toBe(720000)
      expect(payload.reason).toBe('Erreur de saisie sur la quantité')
    })

    it('does not send a reason for a non-financial edit', async () => {
      const wrapper = await mountEdit()
      await wrapper.find('#notes').setValue('note')
      await wrapper.find('form').trigger('submit.prevent')
      await flushPromises()

      expect(updateOrder.mock.calls[0]![1].reason).toBeUndefined()
    })

    it('surfaces the backend minimum-quantity error under the quantity field', async () => {
      const wrapper = await mountEdit()
      updateOrder.mockRejectedValueOnce({
        response: {
          status: 400,
          data: { quantity_litres: ['Quantité minimale autorisée : 500000.00 L'] },
        },
      })
      await wrapper.find('#quantity_litres').setValue('100')
      await wrapper.find('#amend_reason').setValue('Erreur')
      await wrapper.find('form').trigger('submit.prevent')
      await flushPromises()

      expect(wrapper.text()).toContain('Quantité minimale autorisée : 500000.00 L')
    })
  })
})
