import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CustomerLedgerView from '../CustomerLedgerView.vue'

const fetchCustomerLedger = vi.fn()
const exportLedgerPdf = vi.fn()
const exportCustomerPaymentPdf = vi.fn()
const exportInvoicePdf = vi.fn()
const allocateExistingCustomerPayment = vi.fn()
const push = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '1' } }),
  useRouter: () => ({ push }),
}))

vi.mock('../api', () => ({
  fetchCustomerLedger: (...args: unknown[]) => fetchCustomerLedger(...args),
  exportLedgerPdf: (...args: unknown[]) => exportLedgerPdf(...args),
  exportCustomerPaymentPdf: (...args: unknown[]) => exportCustomerPaymentPdf(...args),
  allocateExistingCustomerPayment: (...args: unknown[]) => allocateExistingCustomerPayment(...args),
}))

vi.mock('@/modules/sales/api', () => ({
  exportInvoicePdf: (...args: unknown[]) => exportInvoicePdf(...args),
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
          unallocated_amount: '0.00',
          is_reversed: false,
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

    const proofButton = wrapper
      .findAll('button')
      .find((button) => button.text() === 'Voir justificatif')
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
          sale_detail: {
            quantity_loaded: '45000.00',
            delivered_quantity: '44800.00',
            truck_plates: 'AA-111 / BB-222',
          },
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

  it('shows the truck plates column and a PDF action per invoice row', async () => {
    // Feedback (2026-09-10): the Factures table now has the same per-row
    // PDF action the Paiements table already had, plus the plates of the
    // truck that loaded the invoice.
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
          sale_detail: {
            quantity_loaded: '45000.00',
            delivered_quantity: '44800.00',
            truck_plates: 'AA-111 / BB-222',
          },
        },
      ],
      payments: [],
    })

    const wrapper = mount(CustomerLedgerView)
    await flushPromises()

    expect(wrapper.text()).toContain('AA-111 / BB-222')

    const pdfButton = wrapper.find('[data-test="customer-invoice-pdf"]')
    expect(pdfButton.exists()).toBe(true)

    await pdfButton.trigger('click')
    await flushPromises()

    expect(exportInvoicePdf).toHaveBeenCalledWith(3, 'fr')
    // Clicking the PDF button must not also navigate to the invoice detail
    // page (the whole row is otherwise clickable for that).
    expect(push).not.toHaveBeenCalled()
  })

  it('clearly labels validated unpaid invoices and applies existing credit FIFO', async () => {
    fetchCustomerLedger.mockResolvedValue({
      customer: { id: 1, name: 'Client X', company_name: '' },
      outstanding_balance: '100.00',
      invoices: [
        {
          id: 10,
          invoice_number: 'INV-010',
          status: 'VALIDATED',
          total_amount: '60.00',
          issued_date: '2026-09-01',
          outstanding: '60.00',
        },
        {
          id: 11,
          invoice_number: 'INV-011',
          status: 'VALIDATED',
          total_amount: '40.00',
          issued_date: '2026-09-02',
          outstanding: '40.00',
        },
      ],
      payments: [
        {
          id: 7,
          customer: 1,
          amount: '75.00',
          payment_date: '2026-09-03',
          method: 'CASH',
          reference: '',
          is_indirect: false,
          destination: 'CASH',
          allocations_detail: [],
          unallocated_amount: '75.00',
          is_reversed: false,
          proof_url: null,
        },
      ],
    })
    allocateExistingCustomerPayment.mockResolvedValue({})

    const wrapper = mount(CustomerLedgerView)
    await flushPromises()

    expect(wrapper.text()).toContain('Validée — non payée')
    await wrapper.find('[data-test="allocate-existing-payment"]').trigger('click')
    await flushPromises()

    expect(
      (wrapper.find('[data-test="allocation-amount-10"]').element as HTMLInputElement).value,
    ).toBe('60.00')
    expect(
      (wrapper.find('[data-test="allocation-amount-11"]').element as HTMLInputElement).value,
    ).toBe('15.00')
    await wrapper.find('[data-test="submit-existing-allocation"]').trigger('submit')
    await flushPromises()

    expect(allocateExistingCustomerPayment).toHaveBeenCalledWith(7, [
      { invoice: 10, amount: '60.00' },
      { invoice: 11, amount: '15.00' },
    ])
  })
})
