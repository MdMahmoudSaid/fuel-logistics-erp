import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ManualProfitSection from '../ManualProfitSection.vue'
import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

const list = vi.fn()
const createFn = vi.fn()
const cancelFn = vi.fn()

vi.mock('../api', () => ({
  manualProfitResource: { list: (...a: unknown[]) => list(...a) },
  createManualProfit: (...a: unknown[]) => createFn(...a),
  cancelManualProfit: (...a: unknown[]) => cancelFn(...a),
}))
vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({
    list: vi.fn(async () => ({ count: 1, results: [{ id: 4, name: 'BNP' }] })),
  }),
}))

function row(over: Record<string, unknown> = {}) {
  return {
    id: 7,
    amount: '5000.00',
    date: '2026-10-17',
    note: 'Don',
    bank_account: 4,
    cash_account: null,
    is_cancelled: false,
    cancel_reason: '',
    blocked_reason: null,
    ...over,
  }
}

function mountSection(role = 'Admin') {
  setActivePinia(createPinia())
  useAuthStore().user = { role_detail: { id: 1, name: role, permissions: {} } } as never
  return mount(ManualProfitSection, { global: { plugins: [i18n] } })
}

describe('ManualProfitSection', () => {
  beforeEach(() => {
    list.mockReset().mockResolvedValue({ count: 1, results: [row()] })
    createFn.mockReset().mockResolvedValue(row())
    cancelFn.mockReset().mockResolvedValue(row({ is_cancelled: true }))
  })

  it('lists the added profits', async () => {
    const w = mountSection()
    await flushPromises()
    expect(w.find('[data-test="manual-profit-row-7"]').text()).toContain('Don')
  })

  it('only an admin sees the buttons', async () => {
    const w = mountSection('Operations')
    await flushPromises()
    expect(w.find('[data-test="add-manual-profit"]').exists()).toBe(false)
    expect(w.find('[data-test="cancel-manual-profit-7"]').exists()).toBe(false)
  })

  it('adds a profit on the chosen account and tells the page', async () => {
    const w = mountSection()
    await flushPromises()
    await w.find('[data-test="add-manual-profit"]').trigger('click')
    await w.find('[data-test="manual-profit-amount"]').setValue('250')
    await w.find('[data-test="manual-profit-note"]').setValue('Cadeau')
    await w.find('[data-test="add-manual-profit-dialog"]').trigger('submit')
    await flushPromises()
    expect(createFn).toHaveBeenCalledWith(
      expect.objectContaining({
        amount: '250',
        note: 'Cadeau',
        bank_account: 4,
        cash_account: null,
      }),
    )
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('can add a profit without any account', async () => {
    const w = mountSection()
    await flushPromises()
    await w.find('[data-test="add-manual-profit"]').trigger('click')
    await w.find('[data-test="manual-profit-amount"]').setValue('10')
    await w.find('[data-test="manual-profit-note"]').setValue('x')
    await w.find('[data-test="manual-profit-account"]').setValue('none')
    await w.find('[data-test="add-manual-profit-dialog"]').trigger('submit')
    await flushPromises()
    expect(createFn).toHaveBeenCalledWith(
      expect.objectContaining({ bank_account: null, cash_account: null }),
    )
  })

  it('cancels with a reason; a distributed profit has its button disabled', async () => {
    const w = mountSection()
    await flushPromises()
    await w.find('[data-test="cancel-manual-profit-7"]').trigger('click')
    await w.find('[data-test="cancel-manual-profit-reason"]').setValue('erreur')
    await w.find('[data-test="cancel-manual-profit-dialog"]').trigger('submit')
    await flushPromises()
    expect(cancelFn).toHaveBeenCalledWith(7, 'erreur')

    list.mockResolvedValue({ count: 1, results: [row({ blocked_reason: 'Déjà distribué' })] })
    const w2 = mountSection()
    await flushPromises()
    expect(w2.find('[data-test="cancel-manual-profit-7"]').attributes('disabled')).toBeDefined()
  })
})
