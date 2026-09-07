import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CustomerLedgerView from '../CustomerLedgerView.vue'

const fetchCustomerLedger = vi.fn()
const exportLedgerPdf = vi.fn()
const exportCustomerPaymentPdf = vi.fn()
const push = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '1' } }),
  useRouter: () => ({ push }),
}))

vi.mock('../api', () => ({
  fetchCustomerLedger: (...args: unknown[]) => fetchCustomerLedger(...args),
  exportLedgerPdf: (...args: unknown[]) => exportLedgerPdf(...args),
  exportCustomerPaymentPdf: (...args: unknown[]) => exportCustomerPaymentPdf(...args),
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

  // Recette corrections (2026-09-05): Grand livre client now has the same
  // per-payment PDF action Grand livre transporteur already had.
  it('shows a PDF action per payment row and exports it with the current locale', async () => {
    const wrapper = mount(CustomerLedgerView)
    await flushPromises()

    const pdfButton = wrapper.find('[data-test="customer-payment-pdf"]')
    expect(pdfButton.exists()).toBe(true)

    await pdfButton.trigger('click')
    await flushPromises()

    expect(exportCustomerPaymentPdf).toHaveBeenCalledWith(7, 'fr')
  })

  it('shows loaded and received quantity columns per invoice', async () => {
    fetchCustomerLedger.mockResolvedValue({
      customer: { id: 1, name: 'Client X', company_name: '' },
      outstanding_balance: '0.00',
      invoices: [
        {
          id: 3,
          invoice_number: 'INV-003',
          status: 'PAID',
          total_amount: '900000.00',
          issued_date: '2026-08-10',
          outstanding: '0.00',
          sale_detail: { quantity_loaded: '45000.00', delivered_quantity: '44800.00' },
        },
      ],
      payments: [],
    })

    const wrapper = mount(CustomerLedgerView)
    await flushPromises()

    const text = wrapper.text().replace(/[⁦⁩]/g, '')
    expect(text).toContain('Qté chargée')
    expect(text).toContain('Qté reçue')
    expect(text).toContain('45 000 L')
    expect(text).toContain('44 800 L')
  })
})
