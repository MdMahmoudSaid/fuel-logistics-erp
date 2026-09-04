import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ContributionForm from '../ContributionForm.vue'

const createShareholderContribution = vi.fn()

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    createShareholderContribution: (...args: unknown[]) => createShareholderContribution(...args),
    shareholderResource: {
      list: vi.fn(async () => ({
        count: 2,
        next: null,
        previous: null,
        results: [
          { id: 10, name: 'Ahmed', participation_percent: '50.00', contribution: '0.00', phone: '', notes: '', is_active: true, created_at: '', updated_at: '' },
          { id: 11, name: 'Fatima', participation_percent: '50.00', contribution: '0.00', phone: '', notes: '', is_active: true, created_at: '', updated_at: '' },
        ],
      })),
    },
  }
})

vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({
    list: vi.fn(async () => ({
      count: 1,
      next: null,
      previous: null,
      results: [{ id: 1, name: 'BIM', current_balance: '500000.00' }],
    })),
  }),
}))

describe('ContributionForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    createShareholderContribution.mockResolvedValue({ id: 1 })
  })

  it('lists all shareholders when not locked', async () => {
    const wrapper = mount(ContributionForm)
    await flushPromises()

    const select = wrapper.find('select#shareholder')
    expect(select.text()).toContain('Ahmed')
    expect(select.text()).toContain('Fatima')
    expect((select.element as HTMLSelectElement).disabled).toBe(false)
  })

  it('locks the shareholder when opened from a ledger page', async () => {
    const wrapper = mount(ContributionForm, {
      props: { initialShareholderId: 11, lockShareholder: true },
    })
    await flushPromises()

    const select = wrapper.find('select#shareholder')
    expect((select.element as HTMLSelectElement).disabled).toBe(true)
    expect((select.element as HTMLSelectElement).value).toBe('11')
  })

  // Task 14 (client modifications, 2026-09-04): proof upload is no longer
  // required client-side - the backend already accepts this flow without an
  // attachment.
  it('allows submitting without an attachment', async () => {
    const wrapper = mount(ContributionForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createShareholderContribution).toHaveBeenCalledWith(
      expect.objectContaining({ shareholder: 10, amount: '100000', attachment: null }),
    )
  })

  it('rejects a non-image attachment client-side', async () => {
    const wrapper = mount(ContributionForm)
    await flushPromises()

    const file = new File(['doc'], 'proof.pdf', { type: 'application/pdf' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('form').trigger('submit')

    expect(createShareholderContribution).not.toHaveBeenCalled()
  })

  it('submits a contribution with the chosen account and attachment', async () => {
    const wrapper = mount(ContributionForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('10000000')
    const file = new File(['receipt'], 'recu.jpg', { type: 'image/jpeg' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createShareholderContribution).toHaveBeenCalledWith(
      expect.objectContaining({ shareholder: 10, amount: '10000000', attachment: file }),
    )
  })
})
