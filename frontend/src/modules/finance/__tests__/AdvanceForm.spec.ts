import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdvanceForm from '../AdvanceForm.vue'

const fetchPartyBalances = vi.fn()
const createSupplierAdvance = vi.fn()
const createTransporterAdvance = vi.fn()

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    fetchPartyBalances: (...args: unknown[]) => fetchPartyBalances(...args),
    createSupplierAdvance: (...args: unknown[]) => createSupplierAdvance(...args),
    createTransporterAdvance: (...args: unknown[]) => createTransporterAdvance(...args),
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

describe('AdvanceForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchPartyBalances.mockResolvedValue([
      {
        id: 10,
        label: 'Supplier 1',
        total_due: '0.00',
        open_advances: '0.00',
        net_balance: '0.00',
        last_advance: null,
        last_payment: null,
      },
    ])
    createSupplierAdvance.mockResolvedValue({ id: 1 })
    createTransporterAdvance.mockResolvedValue({ id: 1 })
  })

  it('free mode from the journal only lists parties with a non-negative net balance', async () => {
    fetchPartyBalances.mockResolvedValueOnce([
      {
        id: 10,
        label: 'Debtor Supplier',
        total_due: '500000.00',
        open_advances: '0.00',
        net_balance: '-500000.00',
        last_advance: null,
        last_payment: null,
      },
      {
        id: 11,
        label: 'Eligible Supplier',
        total_due: '0.00',
        open_advances: '0.00',
        net_balance: '0.00',
        last_advance: null,
        last_payment: null,
      },
    ])
    const wrapper = mount(AdvanceForm)
    await flushPromises()

    const partySelect = wrapper.find('select#party')
    expect(partySelect.text()).toContain('Eligible Supplier')
    expect(partySelect.text()).not.toContain('Debtor Supplier')
  })

  it('locks the party and party type when opened from a ledger page', async () => {
    fetchPartyBalances.mockResolvedValueOnce([
      {
        id: 11,
        label: 'Trans A',
        total_due: '0.00',
        open_advances: '0.00',
        net_balance: '0.00',
        last_advance: null,
        last_payment: null,
      },
    ])
    const wrapper = mount(AdvanceForm, {
      props: {
        initialPartyType: 'transporter',
        initialPartyId: 11,
        lockPartyType: true,
        lockParty: true,
      },
    })
    await flushPromises()

    const selects = wrapper.findAll('select')
    expect((selects[0].element as HTMLSelectElement).disabled).toBe(true)
    const partySelect = wrapper.find('select#party')
    expect((partySelect.element as HTMLSelectElement).disabled).toBe(true)
    expect((partySelect.element as HTMLSelectElement).value).toBe('11')
  })

  // Task 14 (client modifications, 2026-09-04): proof upload is no longer
  // required client-side - the backend already accepts this flow without an
  // attachment.
  it('allows submitting without an attachment', async () => {
    const wrapper = mount(AdvanceForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createSupplierAdvance).toHaveBeenCalledWith(
      expect.objectContaining({ supplier: 10, amount: '100000', attachment: null }),
    )
  })

  it('rejects a non-image attachment client-side', async () => {
    const wrapper = mount(AdvanceForm)
    await flushPromises()

    const file = new File(['doc'], 'proof.pdf', { type: 'application/pdf' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')

    await wrapper.find('#amount').setValue('100000')
    await wrapper.find('form').trigger('submit')

    expect(createSupplierAdvance).not.toHaveBeenCalled()
  })

  it('submits a supplier advance with the chosen account and attachment', async () => {
    const wrapper = mount(AdvanceForm)
    await flushPromises()

    await wrapper.find('#amount').setValue('300000')
    const file = new File(['receipt'], 'recu.jpg', { type: 'image/jpeg' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createSupplierAdvance).toHaveBeenCalledWith(
      expect.objectContaining({ supplier: 10, amount: '300000', attachment: file }),
    )
    expect(createTransporterAdvance).not.toHaveBeenCalled()
  })
})
