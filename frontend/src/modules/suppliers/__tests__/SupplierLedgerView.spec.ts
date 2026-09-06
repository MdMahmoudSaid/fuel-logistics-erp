import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import SupplierLedgerView from '../SupplierLedgerView.vue'
import type { SupplierLedger } from '@/modules/purchasing/types'

function setUser(permissions: Record<string, string[]>) {
  const auth = useAuthStore()
  auth.user = {
    id: 1,
    phone: '+22212345678',
    email: 'admin@example.com',
    full_name: 'Admin',
    role: 1,
    role_detail: { id: 1, name: 'Admin', permissions },
  }
}

vi.stubGlobal('confirm', vi.fn(() => true))

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
      is_reversed: false,
    },
    {
      id: 31,
      amount: '50000.00',
      payment_date: '2026-08-21',
      method: 'BANK_TRANSFER',
      is_advance: false,
      reference: 'PAY-NO-PROOF',
      proof_url: null,
      is_reversed: false,
    },
  ],
  total_purchased: '90000000.00',
  total_paid: '0.00',
  outstanding_balance: '90000000.00',
  summary: {
    id: 1,
    label: 'Total',
    total_due: '0.00',
    open_advances: '150000.00',
    net_balance: '150000.00',
    last_advance: { date: '2026-08-20', amount: '150000.00' },
    last_payment: { date: '2026-08-20', amount: '100000.00' },
  },
  entries: [
    {
      type: 'advance_given',
      date: '2026-08-15',
      amount: '150000.00',
      reference: 'ADV-1',
      note: '',
      proof_url: '/media/documents/advance.png',
    },
    {
      type: 'debt_created',
      date: '2026-08-18',
      amount: '60000000.00',
      reference: 'ACH-010',
      note: '',
      proof_url: null,
    },
    {
      type: 'payment',
      date: '2026-08-20',
      amount: '100000.00',
      reference: 'PAY-WITH-PROOF',
      note: '',
      proof_url: null,
    },
  ],
}

const fetchSupplierLedger = vi.fn(async () => ledger)
const exportLedgerPdf = vi.fn(async () => undefined)
const exportSupplierPaymentPdf = vi.fn(async () => undefined)
const cancelSupplierPayment = vi.fn(async () => ({ ...ledger.payments[0], is_reversed: true }))

vi.mock('@/modules/purchasing/api', () => ({
  fetchSupplierLedger: (...args: unknown[]) => fetchSupplierLedger(...(args as [])),
}))

vi.mock('@/modules/finance/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/finance/api')>()
  return {
    ...actual,
    exportLedgerPdf: (...args: unknown[]) => exportLedgerPdf(...(args as [])),
    exportSupplierPaymentPdf: (...args: unknown[]) => exportSupplierPaymentPdf(...(args as [])),
    cancelSupplierPayment: (...args: unknown[]) => cancelSupplierPayment(...(args as [])),
  }
})

describe('SupplierLedgerView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Task 6 (client business decision, confirmed 2026-09-06): the view
    // now reads useAuthStore() for the supplier-payment cancel button's
    // permission gate, so a Pinia instance must exist before mounting.
    setActivePinia(createPinia())
  })

  it('shows purchase proofs in the purchase history table with an internal preview modal', async () => {
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    expect(wrapper.text()).toContain('Justificatif')
    expect(wrapper.text()).toContain('Voir justificatif')
    expect(wrapper.text()).toContain('—')
    expect(wrapper.find('a[target="_blank"]').exists()).toBe(false)

    const proofButton = wrapper
      .findAll('button')
      .find((button) => button.text() === 'Voir justificatif')
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

    const proofButtons = wrapper
      .findAll('button')
      .filter((button) => button.text() === 'Voir justificatif')
    await proofButtons[1].trigger('click')
    await flushPromises()

    expect(push).not.toHaveBeenCalled()
    expect(wrapper.find('img[src="/media/documents/supplier-payment.png"]').exists()).toBe(true)
  })

  it('shows the 4 balance cards from summary and a Nouvelle avance button when net_balance >= 0', async () => {
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    expect(wrapper.text()).toContain('Total dû')
    expect(wrapper.text()).toContain('Avances ouvertes')
    expect(wrapper.text()).toContain('Solde net')
    expect(wrapper.text()).toContain('Dernière opération')
    const buttons = wrapper.findAll('button').map((button) => button.text())
    expect(buttons).toContain('Nouvelle avance')
    expect(buttons).not.toContain('Enregistrer un paiement')
  })

  it('does not show the old redundant grid1 cards', async () => {
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    expect(wrapper.text()).not.toContain('Total acheté')
    expect(wrapper.text()).not.toContain('Total payé')
    expect(wrapper.text()).not.toContain('Solde impayé')
    expect(wrapper.text()).not.toContain('Dernier paiement')
  })

  it('collapses last_advance/last_payment into a single Dernière opération line', async () => {
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    // fixture: last_advance and last_payment share the same date, advance wins the tie
    const text = wrapper.text().replace(/[⁦⁩]/g, '')
    expect(text).toContain('Avance: 150 000 XOF')
    expect(text).not.toContain('Paiement: 100 000 XOF')
  })

  it('opens AdvanceForm locked to this supplier when Nouvelle avance is clicked', async () => {
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    const advanceButton = wrapper
      .findAll('button')
      .find((button) => button.text() === 'Nouvelle avance')
    expect(advanceButton).toBeTruthy()
    await advanceButton!.trigger('click')
    await flushPromises()
    // AdvanceForm's own onMounted fetch (bankAccountResource/
    // cashAccountResource/fetchPartyBalances) is a real, unmocked
    // apiClient call in this spec. Its request interceptor calls
    // useAuthStore() - before Pinia was required here (pre-Task 6), that
    // call threw synchronously with no active Pinia, which rejected the
    // request near-instantly and cleared "loading" within one
    // flushPromises(). Now that Pinia is active for this whole file, the
    // interceptor succeeds and a real (failing) network call goes out,
    // which needs real wall-clock time to settle - wait for it instead of
    // guessing a flush count.
    await vi.waitFor(() => {
      expect(wrapper.find('select#party').exists()).toBe(true)
    })

    const selects = wrapper.findAll('select')
    expect((selects[0].element as HTMLSelectElement).disabled).toBe(true)
    const partySelect = wrapper.find('select#party')
    expect(partySelect.exists()).toBe(true)
    expect((partySelect.element as HTMLSelectElement).disabled).toBe(true)
  })

  it('renders the chronological entries table and opens a proof in the internal modal', async () => {
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    expect(wrapper.text()).toContain('Avance versée')
    expect(wrapper.text()).toContain('Dette créée')
    expect(wrapper.text()).toContain('Paiement complémentaire')

    const proofButtons = wrapper
      .findAll('button')
      .filter((button) => button.text() === 'Voir justificatif')
    await proofButtons[proofButtons.length - 1].trigger('click')
    await flushPromises()

    expect(wrapper.find('img[src="/media/documents/advance.png"]').exists()).toBe(true)
  })

  it('shows Imprimer and Exporter PDF buttons and exports the ledger with the current locale', async () => {
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    const buttons = wrapper.findAll('button')
    const printButton = buttons.find((button) => button.text() === 'Imprimer')
    const exportButton = buttons.find((button) => button.text() === 'Exporter PDF')
    expect(printButton).toBeTruthy()
    expect(exportButton).toBeTruthy()

    await exportButton!.trigger('click')
    await flushPromises()

    expect(exportLedgerPdf).toHaveBeenCalledWith('supplier', 1, 'fr')
  })

  // Recette corrections (2026-09-05): Grand livre fournisseur now has the
  // same per-payment PDF action Grand livre transporteur already had.
  it('shows a PDF action per payment row and exports it with the current locale', async () => {
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    const pdfButtons = wrapper.findAll('[data-test="supplier-payment-pdf"]')
    expect(pdfButtons).toHaveLength(2)

    await pdfButtons[0].trigger('click')
    await flushPromises()

    expect(exportSupplierPaymentPdf).toHaveBeenCalledWith(30, 'fr')
  })

  // Task 6 (client business decision, confirmed 2026-09-06): a supplier
  // payment can only be corrected by contre-passation - never a silent
  // edit or delete - via a permission-gated "Annuler" button per row.
  it('hides the Annuler button without finance.cancel permission', async () => {
    setUser({ finance: ['view'] })
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()

    expect(wrapper.find('[data-test="supplier-payment-cancel"]').exists()).toBe(false)
  })

  it('cancels a supplier payment after confirmation and reloads the ledger', async () => {
    setUser({ finance: ['view', 'cancel'] })
    const wrapper = mount(SupplierLedgerView)
    await flushPromises()
    fetchSupplierLedger.mockClear()

    const cancelButtons = wrapper.findAll('[data-test="supplier-payment-cancel"]')
    expect(cancelButtons).toHaveLength(2)

    await cancelButtons[0].trigger('click')
    await flushPromises()

    expect(cancelSupplierPayment).toHaveBeenCalledWith(30)
    expect(fetchSupplierLedger).toHaveBeenCalledTimes(1)
  })
})
