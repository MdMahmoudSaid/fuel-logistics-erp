import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import CessionLetterForm from '../CessionLetterForm.vue'
import type { SupplierOrder } from '../types'

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

// Order: 100,000 L purchased, 60,000 L already allocated to other cessions
// (reliquat = 40,000 L). This is exactly the spec §6 worked example.
const ORDER: SupplierOrder = {
  id: 5,
  reference: 'SO-005',
  supplier: 1,
  supplier_detail: { id: 1, name: 'Total', company_name: '', country: 'Senegal' },
  product: 1,
  product_detail: { id: 1, name: 'Gasoil', code: 'gasoil' },
  purchase_date: '2026-08-18',
  quantity_litres: '100000.00',
  unit_price: '600.0000',
  currency: 'XOF',
  total_amount: '60000000.00',
  optional_costs: null,
  notes: '',
  status: 'CONFIRMED',
  created_by: 1,
  created_by_detail: null,
  reliquat: '40000.00',
  loaded_quantity: '0.00',
  documents: [],
  cessions: [],
  created_at: '',
  updated_at: '',
}

const create = vi.fn()
const uploadDocument = vi.fn()
const fetchNextCessionLetterReference = vi.fn(async () => 'CES-202608-0003')
vi.mock('../api', () => ({
  supplierOrderResource: {
    get: vi.fn(async () => ORDER),
    list: vi.fn(async () => paginated([])),
  },
  cessionLetterResource: {
    get: vi.fn(),
    create: (payload: Record<string, unknown>) => create(payload),
    update: vi.fn(),
    list: vi.fn(),
  },
  uploadDocument: (payload: Record<string, unknown>) => uploadDocument(payload),
  fetchNextCessionLetterReference: () => fetchNextCessionLetterReference(),
}))

function makeRouter(query: Record<string, string> = {}) {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/cession-letters/new', name: 'cession-letter-new', component: CessionLetterForm },
      { path: '/cession-letters/:id', name: 'cession-letter-detail', component: stub },
      { path: '/supplier-orders', name: 'supplier-orders', component: stub },
    ],
  })
  router.push({ name: 'cession-letter-new', query })
  return router
}

describe('CessionLetterForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('pre-fills the reference as a read-only, server-generated value', async () => {
    const router = makeRouter({ supplier_order: '5' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    const input = wrapper.find<HTMLInputElement>('#reference')
    expect(input.attributes('disabled')).toBeDefined()
    expect(input.element.value).toBe('CES-202608-0003')
    expect(fetchNextCessionLetterReference).toHaveBeenCalled()
  })

  it('surfaces any field error, not just authorized_quantity', async () => {
    create.mockRejectedValueOnce({
      response: { status: 400, data: { issue_date: ['Ce champ est requis.'] } },
    })
    const router = makeRouter({ supplier_order: '5' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#authorized_quantity').setValue('1000')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Ce champ est requis.')
  })

  it('shows allocation details, default status and proof upload before first save', async () => {
    const router = makeRouter({ supplier_order: '5' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#authorized_quantity').setValue('30000')
    await flushPromises()

    const text = wrapper.text().replace(/[⁦⁩]/g, '')
    expect(text).toContain('Contre la commande')
    expect(text).toContain('SO-005')
    expect(text).toContain('Acheté : 100 000 L')
    expect(text).toContain('Déjà alloué : 60 000 L')
    expect(text).toContain('Demandé : 30 000 L')
    expect(text).toContain('10 000 L resteraient disponibles')
    expect(text).toContain('Statut')
    expect(text).toContain('Active')
    expect(text).toContain('Justificatif')
    expect(wrapper.find('input[type="file"]').exists()).toBe(true)
  })

  it('uploads a selected image automatically after creating the cession letter', async () => {
    create.mockResolvedValueOnce({ id: 17 })
    uploadDocument.mockResolvedValueOnce(undefined)
    const router = makeRouter({ supplier_order: '5' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    const file = new File(['jpg'], 'cession.jpg', { type: 'image/jpeg' })
    const input = wrapper.find<HTMLInputElement>('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')

    await wrapper.find('#authorized_quantity').setValue('30000')
    await wrapper.find('#issue_date').setValue('2026-08-20')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(create).toHaveBeenCalled()
    expect(uploadDocument).toHaveBeenCalledWith(
      expect.objectContaining({
        file,
        documentType: 'cession_proof',
        contentTypeName: 'cessionletter',
        objectId: 17,
      }),
    )
  })

  it('rejects a PDF proof before calling the API', async () => {
    const router = makeRouter({ supplier_order: '5' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    const input = wrapper.find<HTMLInputElement>('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['pdf'], 'cession.pdf', { type: 'application/pdf' })],
      configurable: true,
    })
    await input.trigger('change')

    expect(wrapper.text()).toContain('Seules les images JPG, JPEG, PNG ou WEBP sont autorisées.')
    expect(uploadDocument).not.toHaveBeenCalled()
  })
})

describe('CessionLetterForm live allocation bar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the remaining reliquat and no warning for a request within the limit', async () => {
    const router = makeRouter({ supplier_order: '5' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('#authorized_quantity').setValue('30000')
    await flushPromises()

    // Quantities are wrapped in bidi isolate marks (LRI/PDI) so they can't be
    // reordered in RTL locales; strip them before matching adjacent text.
    const text = wrapper.text().replace(/[⁦⁩]/g, '')
    expect(text).toContain('10 000 L resteraient disponibles')
    expect(text).not.toContain('Dépasse le reliquat disponible')
  })

  it('warns immediately when the requested quantity exceeds the reliquat', async () => {
    const router = makeRouter({ supplier_order: '5' })
    await router.isReady()
    const wrapper = mount(CessionLetterForm, { global: { plugins: [router] } })
    await flushPromises()

    // spec §6 worked example: 40,000 L remaining, requesting 45,000 L must warn.
    await wrapper.find('#authorized_quantity').setValue('45000')
    await flushPromises()

    // Quantities are wrapped in bidi isolate marks (LRI/PDI) so they can't be
    // reordered in RTL locales; strip them before matching adjacent text.
    expect(wrapper.text().replace(/[⁦⁩]/g, '')).toContain('Dépasse le reliquat disponible de 5 000 L')
  })
})
