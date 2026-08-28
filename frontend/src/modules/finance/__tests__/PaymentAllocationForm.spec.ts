import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import PaymentAllocationForm from '../PaymentAllocationForm.vue'
import type { CustomerLedgerInvoice } from '../types'

function findAllTyped<T extends Element>(
  wrapper: ReturnType<typeof mount>,
  selector: string,
): DOMWrapper<T>[] {
  return wrapper.findAll(selector) as unknown as DOMWrapper<T>[]
}

function paginated<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results }
}

const customers = [{ id: 1, name: 'Client X', company_name: '' }]

vi.mock('@/api/resource', () => ({
  createResourceApi: vi.fn((path: string) => ({
    list: vi.fn(async () => paginated(path === '/customers/' ? customers : [])),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  })),
}))

function makeInvoice(overrides: Partial<CustomerLedgerInvoice> = {}): CustomerLedgerInvoice {
  return {
    id: 1,
    invoice_number: 'FAC-0001',
    status: 'VALIDATED',
    total_amount: '500.00',
    issued_date: '2024-01-01',
    outstanding: '500.00',
    ...overrides,
  }
}

let ledgerInvoices: CustomerLedgerInvoice[] = []
const fetchCustomerLedger = vi.fn(async (_id: number) => ({
  customer: { id: 1, name: 'Client X', company_name: '' },
  outstanding_balance: '0.00',
  invoices: ledgerInvoices,
  payments: [],
}))
const createCustomerPayment = vi.fn(async (p: Record<string, unknown>) => ({ id: 1, ...p }))
vi.mock('../api', () => ({
  createCustomerPaymentWithProof: (p: Record<string, unknown>) => createCustomerPayment(p),
  fetchCustomerLedger: (id: number) => fetchCustomerLedger(id),
  uploadCustomerPaymentProof: vi.fn(async () => undefined),
}))

async function selectCustomer(wrapper: ReturnType<typeof mount>) {
  await wrapper.find('#customer').setValue('1')
  await flushPromises()
}

describe('PaymentAllocationForm FIFO auto-allocation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // invoice A is older than invoice B - FIFO must pick A first
    ledgerInvoices = [
      makeInvoice({
        id: 2,
        invoice_number: 'FAC-0002',
        issued_date: '2024-02-01',
        outstanding: '1000.00',
      }),
      makeInvoice({
        id: 1,
        invoice_number: 'FAC-0001',
        issued_date: '2024-01-01',
        outstanding: '500.00',
      }),
    ]
  })

  it('fills the oldest unpaid invoice first, then the next, once amount and customer are set', async () => {
    const wrapper = mount(PaymentAllocationForm)
    await flushPromises()
    await selectCustomer(wrapper)

    await wrapper.find('#amount').setValue('600')
    await flushPromises()

    const lineInvoiceSelects = findAllTyped<HTMLSelectElement>(wrapper, '[data-test="line-invoice"]')
    const amountInputs = findAllTyped<HTMLInputElement>(wrapper, '[data-test="line-amount"]')
    // first allocation line should target the oldest invoice (id 1), fully covering it (500)
    expect(lineInvoiceSelects[0].element.value).toBe('1')
    expect(amountInputs[0].element.value).toBe('500.00')
    // remainder (100) goes to the next-oldest invoice (id 2)
    expect(lineInvoiceSelects[1].element.value).toBe('2')
    expect(amountInputs[1].element.value).toBe('100.00')
  })

  it('puts any amount left over past total outstanding into an unallocated-credit line', async () => {
    const wrapper = mount(PaymentAllocationForm)
    await flushPromises()
    await selectCustomer(wrapper)

    await wrapper.find('#amount').setValue('2000')
    await flushPromises()

    const invoiceSelects = findAllTyped<HTMLSelectElement>(wrapper, '[data-test="line-invoice"]')
    const amountInputs = findAllTyped<HTMLInputElement>(wrapper, '[data-test="line-amount"]')
    expect(invoiceSelects).toHaveLength(3)
    expect(invoiceSelects[2].element.value).toBe('')
    expect(amountInputs[2].element.value).toBe('500.00')
  })

  it('stops overwriting lines the user edited manually once the global amount changes again', async () => {
    const wrapper = mount(PaymentAllocationForm)
    await flushPromises()
    await selectCustomer(wrapper)

    await wrapper.find('#amount').setValue('600')
    await flushPromises()

    const amountInputs = () => findAllTyped<HTMLInputElement>(wrapper, '[data-test="line-amount"]')
    await amountInputs()[0].setValue('123.45')
    await flushPromises()

    // changing the global amount again must NOT wipe out the manual edit
    await wrapper.find('#amount').setValue('700')
    await flushPromises()

    expect(amountInputs()[0].element.value).toBe('123.45')
  })

  it('recomputes FIFO from scratch when the auto-allocate button is clicked again', async () => {
    const wrapper = mount(PaymentAllocationForm)
    await flushPromises()
    await selectCustomer(wrapper)

    await wrapper.find('#amount').setValue('600')
    await flushPromises()

    const amountInputs = () => findAllTyped<HTMLInputElement>(wrapper, '[data-test="line-amount"]')
    await amountInputs()[0].setValue('123.45')
    await flushPromises()

    await wrapper.find('[data-test="auto-allocate"]').trigger('click')
    await flushPromises()

    expect(amountInputs()[0].element.value).toBe('500.00')
  })

  it('refuses to save a customer payment without a proof document', async () => {
    const wrapper = mount(PaymentAllocationForm)
    await flushPromises()
    await selectCustomer(wrapper)

    await wrapper.find('#amount').setValue('600')
    await wrapper.find('#cash_account').setValue('1')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Le justificatif de paiement est obligatoire.')
    expect(createCustomerPayment).not.toHaveBeenCalled()
  })

  it('shows a clear payment proof picker and selected file name', async () => {
    const wrapper = mount(PaymentAllocationForm)
    await flushPromises()

    expect(wrapper.text()).toContain('Justificatif de paiement')
    expect(wrapper.text()).toContain('Choisir un fichier')

    const file = new File(['receipt'], 'recu-client.png', { type: 'image/png' })
    Object.defineProperty(wrapper.find('#proof_file').element, 'files', {
      value: [file],
      configurable: true,
    })
    await wrapper.find('#proof_file').trigger('change')

    expect(wrapper.text()).toContain('recu-client.png')
  })
})
