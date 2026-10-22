import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ContributionsSection from '../ContributionsSection.vue'
import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

const list = vi.fn()
const cancelFn = vi.fn()
const updateFn = vi.fn()

vi.mock('../api', () => ({
  shareholderContributionResource: { list: (...a: unknown[]) => list(...a) },
  cancelShareholderContribution: (...a: unknown[]) => cancelFn(...a),
  updateShareholderContribution: (...a: unknown[]) => updateFn(...a),
}))
vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({
    list: vi.fn(async () => ({ count: 1, results: [{ id: 1, name: 'BNP' }] })),
  }),
}))

function row(over: Record<string, unknown> = {}) {
  return {
    id: 7,
    shareholder: 1,
    shareholder_detail: { id: 1, name: 'a' },
    amount: '179000000.00',
    amount_returned: '0.00',
    remaining_capital: '179000000.00',
    date: '2026-10-01',
    bank_account: 1,
    cash_account: null,
    reference: '',
    notes: '',
    proof_url: null,
    is_cancelled: false,
    cancel_reason: '',
    blocked_reason: null,
    ...over,
  }
}

const holders = [
  { id: 1, name: 'a' },
  { id: 2, name: 'b' },
] as never

function mountSection(role = 'Admin') {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.user = { role_detail: { id: 1, name: role, permissions: {} } } as never
  return mount(ContributionsSection, {
    props: { shareholders: holders },
    global: { plugins: [i18n] },
  })
}

describe('ContributionsSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    i18n.global.locale.value = 'fr'
    list.mockResolvedValue({ count: 1, results: [row()] })
  })

  it('cancels an apport with a mandatory reason (admin)', async () => {
    cancelFn.mockResolvedValue(row({ is_cancelled: true }))
    const w = mountSection()
    await flushPromises()
    await w.find('[data-test="cancel-contribution-7"]').trigger('click')
    const confirm = w.find('[data-test="confirm-cancel-contribution"]')
    expect(confirm.attributes('disabled')).toBeDefined()
    await w.find('[data-test="cancel-contribution-reason"]').setValue('Mauvais associé')
    await w.find('[data-test="cancel-contribution-dialog"]').trigger('submit')
    await flushPromises()
    expect(cancelFn).toHaveBeenCalledWith(7, 'Mauvais associé')
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('hides the cancel button for non-admin roles but keeps edit', async () => {
    const w = mountSection('Finance')
    await flushPromises()
    expect(w.find('[data-test="cancel-contribution-7"]').exists()).toBe(false)
    expect(w.find('[data-test="edit-contribution-7"]').exists()).toBe(true)
  })

  it('disables cancel with the backend reason when partly withdrawn', async () => {
    list.mockResolvedValue({
      count: 1,
      results: [row({ amount_returned: '10.00', blocked_reason: 'Déjà retiré' })],
    })
    const w = mountSection()
    await flushPromises()
    const btn = w.find('[data-test="cancel-contribution-7"]')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.attributes('title')).toBe('Déjà retiré')
  })

  it('shows cancelled rows without actions', async () => {
    list.mockResolvedValue({
      count: 1,
      results: [row({ is_cancelled: true, cancel_reason: 'erreur' })],
    })
    const w = mountSection()
    await flushPromises()
    expect(w.text()).toContain('Annulé')
    expect(w.find('[data-test="edit-contribution-7"]').exists()).toBe(false)
  })

  it('moves an apport to another associate and requires a reason', async () => {
    updateFn.mockResolvedValue(row({ shareholder: 2 }))
    const w = mountSection()
    await flushPromises()
    await w.find('[data-test="edit-contribution-7"]').trigger('click')
    await w.find('#edit_contribution_shareholder').setValue('2')
    const save = w.find('[data-test="save-contribution"]')
    expect(save.attributes('disabled')).toBeDefined()
    await w.find('[data-test="edit-contribution-reason"]').setValue('Erreur de saisie')
    await w.find('[data-test="edit-contribution-dialog"]').trigger('submit')
    await flushPromises()
    expect(updateFn).toHaveBeenCalledWith(7, {
      shareholder: 2,
      date: '2026-10-01',
      reason: 'Erreur de saisie',
      reference: '',
      notes: '',
    })
  })

  it('corrects the amount (pre-filled, reason required) and sends it', async () => {
    updateFn.mockResolvedValue(row({ amount: '1000000.00' }))
    const w = mountSection()
    await flushPromises()
    await w.find('[data-test="edit-contribution-7"]').trigger('click')
    const amount = w.find('[data-test="edit-contribution-amount"]')
    expect((amount.element as HTMLInputElement).value).toBe('179000000')
    await amount.setValue('1000000')
    expect(w.find('[data-test="save-contribution"]').attributes('disabled')).toBeDefined()
    await w.find('[data-test="edit-contribution-reason"]').setValue('Erreur de saisie')
    await w.find('[data-test="edit-contribution-dialog"]').trigger('submit')
    await flushPromises()
    expect(updateFn).toHaveBeenCalledWith(7, {
      shareholder: 1,
      date: '2026-10-01',
      amount: '1000000',
      reason: 'Erreur de saisie',
      reference: '',
      notes: '',
    })
  })

  it('locks the amount for non-admins and once part of it was withdrawn', async () => {
    let w = mountSection('Finance')
    await flushPromises()
    await w.find('[data-test="edit-contribution-7"]').trigger('click')
    expect(w.find('[data-test="edit-contribution-amount"]').attributes('disabled')).toBeDefined()

    list.mockResolvedValue({
      count: 1,
      results: [row({ amount_returned: '10.00', blocked_reason: 'Déjà retiré' })],
    })
    w = mountSection()
    await flushPromises()
    await w.find('[data-test="edit-contribution-7"]').trigger('click')
    expect(w.find('[data-test="edit-contribution-amount"]').attributes('disabled')).toBeDefined()
  })
})
