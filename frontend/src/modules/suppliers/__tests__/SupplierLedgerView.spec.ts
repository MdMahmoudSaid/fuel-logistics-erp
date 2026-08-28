import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import SupplierLedgerView from '../SupplierLedgerView.vue'
import type { SupplierLedger } from '@/modules/purchasing/types'

const push = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '1' } }),
  useRouter: () => ({ push }),
}))

const ledger: SupplierLedger = {
  supplier: { id: 1, name: 'Total' },
  orders: [
    {
      id: 10,
      reference: 'ACH-010',
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
      reliquat: '55000.00',
      loaded_quantity: '0.00',
      documents: [
        {
          id: 3,
          file: '/media/documents/achat.png',
          document_type: 'purchase_contract',
          reference: '',
          uploaded_by: 1,
          uploaded_by_email: 'admin@example.com',
          created_at: '',
        },
      ],
      cessions: [],
      created_at: '',
      updated_at: '',
    },
    {
      id: 11,
      reference: 'ACH-011',
      supplier: 1,
      supplier_detail: { id: 1, name: 'Total', company_name: '', country: 'Senegal' },
      product: 1,
      product_detail: { id: 1, name: 'Gasoil', code: 'gasoil' },
      purchase_date: '2026-08-19',
      quantity_litres: '50000.00',
      unit_price: '600.0000',
      currency: 'XOF',
      total_amount: '30000000.00',
      optional_costs: null,
      notes: '',
      status: 'DRAFT',
      created_by: 1,
      created_by_detail: null,
      reliquat: '50000.00',
      loaded_quantity: '0.00',
      documents: [],
      cessions: [],
      created_at: '',
      updated_at: '',
    },
  ],
  reliquat_summary: [],
  payments: [
    {
      id: 30,
      amount: '100000.00',
      payment_date: '2026-08-20',
      method: 'BANK_TRANSFER',
      is_advance: false,
      reference: 'PAY-WITH-PROOF',
      proof_url: '/media/documents/supplier-payment.png',
    },
    {
      id: 31,
      amount: '50000.00',
      payment_date: '2026-08-21',
      method: 'BANK_TRANSFER',
      is_advance: false,
      reference: 'PAY-NO-PROOF',
      proof_url: null,
    },
  ],
  total_purchased: '90000000.00',
  total_paid: '0.00',
  outstanding_balance: '90000000.00',
}

const fetchSupplierLedger = vi.fn(async () => ledger)

vi.mock('@/modules/purchasing/api', () => ({
  fetchSupplierLedger: (...args: unknown[]) => fetchSupplierLedger(...(args as [])),
}))

describe('SupplierLedgerView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows purchase proofs in the purchase history table with an internal preview modal', async () => {
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    expect(wrapper.text()).toContain('Justificatif')
    expect(wrapper.text()).toContain('Voir justificatif')
    expect(wrapper.text()).toContain('—')
    expect(wrapper.find('a[target="_blank"]').exists()).toBe(false)

    const proofButton = wrapper.findAll('button').find((button) => button.text() === 'Voir justificatif')
    expect(proofButton).toBeTruthy()
    await proofButton!.trigger('click')
    await flushPromises()

    expect(push).not.toHaveBeenCalled()
    expect(wrapper.find('img[src="/media/documents/achat.png"]').exists()).toBe(true)
  })

  it('shows supplier payment proofs in payments and advances with an internal preview modal', async () => {
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    const paymentSectionText = wrapper.text()
    expect(paymentSectionText).toContain('PAY-WITH-PROOF')
    expect(paymentSectionText).toContain('PAY-NO-PROOF')
    expect(paymentSectionText).toContain('Voir justificatif')
    expect(wrapper.find('a[target="_blank"]').exists()).toBe(false)

    const proofButtons = wrapper.findAll('button').filter((button) => button.text() === 'Voir justificatif')
    await proofButtons[1].trigger('click')
    await flushPromises()

    expect(push).not.toHaveBeenCalled()
    expect(wrapper.find('img[src="/media/documents/supplier-payment.png"]').exists()).toBe(true)
  })
})
