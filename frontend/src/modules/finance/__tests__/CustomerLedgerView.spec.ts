import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CustomerLedgerView from '../CustomerLedgerView.vue'

const fetchCustomerLedger = vi.fn()
const exportLedgerPdf = vi.fn()
const push = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '1' } }),
  useRouter: () => ({ push }),
}))

vi.mock('../api', () => ({
  fetchCustomerLedger: (...args: unknown[]) => fetchCustomerLedger(...args),
  exportLedgerPdf: (...args: unknown[]) => exportLedgerPdf(...args),
}))

describe('CustomerLedgerView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchCustomerLedger.mockResolvedValue({
      customer: { id: 1, name: 'Client X', company_name: '' },
      outstanding_balance: '0.00',
      invoices: [],
      payments: [
        {
          id: 7,
          customer: 1,
          customer_detail: { id: 1, name: 'Client X', company_name: '' },
          amount: '150000.00',
          payment_date: '2026-08-18',
          method: 'CASH',
          bank_account: null,
          cash_account: 1,
          reference: 'PAY-001',
          is_indirect: false,
          destination: 'CASH',
          note: '',
          recorded_by: 1,
          recorded_by_detail: null,
          allocations_detail: [],
          proof_url: '/media/documents/recu.jpg',
          created_at: '',
          updated_at: '',
        },
      ],
    })
  })

  it('opens payment proof inside an internal preview modal, not a new tab', async () => {
    const wrapper = mount(CustomerLedgerView)
    await flushPromises()

    expect(wrapper.find('a[target="_blank"]').exists()).toBe(false)

    const proofButton = wrapper.findAll('button').find((button) => button.text() === 'Voir justificatif')
    expect(proofButton).toBeTruthy()
    await proofButton!.trigger('click')
    await flushPromises()

    expect(wrapper.find('img[src="/media/documents/recu.jpg"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Fermer')
  })

  it('shows Imprimer and Exporter PDF buttons and exports with the current locale', async () => {
    const wrapper = mount(CustomerLedgerView)
    await flushPromises()

    const buttons = wrapper.findAll('button')
    const printButton = buttons.find((button) => button.text() === 'Imprimer')
    const exportButton = buttons.find((button) => button.text() === 'Exporter PDF')
    expect(printButton).toBeTruthy()
    expect(exportButton).toBeTruthy()

    await exportButton!.trigger('click')
    await flushPromises()

    expect(exportLedgerPdf).toHaveBeenCalledWith('customer', 1, 'fr')
  })
})
