import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type {
  AllocatableKind,
  AllocatableTypeMap,
  CustomerLedger,
  CustomerPayment,
  DebtPaymentResult,
  DebtPaymentType,
  Expense,
  PartyBalance,
  PartyType,
  Shareholder,
  ShareholderLedger,
  ShareholderLoan,
  ShareholderProfitDistribution,
  ShareholderProfitPreview,
  ShareholderWithdrawal,
  SupplierAdvance,
  SupplierPayment,
  TransporterAdvance,
  TransporterLedger,
  TransportPayment,
  TreasuryTransaction,
  PayableDebt,
} from './types'

export const customerPaymentResource = createResourceApi<CustomerPayment>('/customer-payments/')
export const supplierPaymentResource = createResourceApi<SupplierPayment>('/supplier-payments/')
export const supplierAdvanceResource = createResourceApi<SupplierAdvance>('/supplier-advances/')
export const transporterAdvanceResource =
  createResourceApi<TransporterAdvance>('/transporter-advances/')
export const transportPaymentResource = createResourceApi<TransportPayment>('/transport-payments/')
export const expenseResource = createResourceApi<Expense>('/expenses/')

// GET /api/allocatable-types/ (backend/apps/finance/views.py
// AllocatableTypesViewSet) - kind -> ContentType PK lookup the allocation
// picker needs to turn a human choice into the numeric content_type
// ExpenseAllocationInputSerializer expects.
export function fetchAllocatableTypes(): Promise<AllocatableTypeMap> {
  return apiClient
    .get<{ kind: AllocatableKind; content_type: number }[]>('/allocatable-types/')
    .then((r) => Object.fromEntries(r.data.map((row) => [row.kind, row.content_type])))
}
export const treasuryTransactionResource =
  createResourceApi<TreasuryTransaction>('/treasury-transactions/')

export function fetchCustomerLedger(customerId: number): Promise<CustomerLedger> {
  return apiClient.get<CustomerLedger>(`/customers/${customerId}/ledger/`).then((r) => r.data)
}

// Generic attachment upload (backend/apps/documents), scoped to the one
// document_type/content_type this module needs: a proof image attached to
// an already-created CustomerPayment (backend/apps/documents/views.py
// DocumentViewSet resolves its module permission from content_type_name,
// so a Finance-only role can post here without needing "purchasing" too).
export function uploadCustomerPaymentProof(params: {
  file: File
  objectId: number
}): Promise<void> {
  const form = new FormData()
  form.append('file', params.file)
  form.append('document_type', 'customer_payment_proof')
  form.append('content_type_name', 'customerpayment')
  form.append('object_id', String(params.objectId))
  return apiClient
    .post('/documents/', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then(() => undefined)
}

export function createCustomerPaymentWithProof(
  payload: Record<string, unknown>,
  proof: File,
): Promise<CustomerPayment> {
  const form = new FormData()
  for (const [key, value] of Object.entries(payload)) {
    if (value === undefined || value === null) continue
    if (Array.isArray(value)) {
      form.append(key, JSON.stringify(value))
    } else {
      form.append(key, String(value))
    }
  }
  form.append('proof', proof)
  return apiClient
    .post<CustomerPayment>('/customer-payments/', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}

export function fetchTransporterLedger(transporterId: number): Promise<TransporterLedger> {
  return apiClient
    .get<TransporterLedger>(`/transporters/${transporterId}/ledger/`)
    .then((r) => r.data)
}

// backend/apps/finance/services.py IndirectSettlementService.record_indirect_payment()
// is the sole authority on this flow (Expense + CustomerPayment + PaymentAllocation,
// never a TreasuryTransaction) - this just posts the request.
export function recordIndirectExpense(payload: {
  customer: number
  invoice?: number | null
  category: string
  amount: string
  calculation_method?: string
  date: string
  reference?: string
  notes?: string
}): Promise<{ expense: Expense; payment: CustomerPayment; allocation_id: number }> {
  return apiClient
    .post('/expenses/record-indirect/', payload)
    .then((r) => r.data as { expense: Expense; payment: CustomerPayment; allocation_id: number })
}

// backend/apps/finance/services.py TreasuryService.record_transfer() is the sole
// authority on this flow (matched MONEY_OUT/MONEY_IN TRANSFER pair under
// account locks) - this just posts the request.
export function recordTransfer(payload: {
  source_account_type: 'bank' | 'cash'
  source_account_id: number
  dest_account_type: 'bank' | 'cash'
  dest_account_id: number
  amount: string
  date: string
  reference?: string
}): Promise<{ money_out: TreasuryTransaction; money_in: TreasuryTransaction }> {
  return apiClient
    .post('/treasury-transactions/transfer/', payload)
    .then((r) => r.data as { money_out: TreasuryTransaction; money_in: TreasuryTransaction })
}

export function fetchPayableDebts(debtType: DebtPaymentType): Promise<PayableDebt[]> {
  return apiClient
    .get<PayableDebt[]>('/treasury-transactions/payable-debts/', {
      params: { debt_type: debtType },
    })
    .then((r) => r.data)
}

export function recordDebtPayment(payload: {
  debt_type: DebtPaymentType
  debt_id: number
  bank_account: number
  amount: string
  date: string
  reference?: string
  note?: string
  attachment?: File | null
}): Promise<DebtPaymentResult> {
  const { attachment, ...fields } = payload
  if (!attachment) {
    return apiClient
      .post<DebtPaymentResult>('/treasury-transactions/record-debt-payment/', fields)
      .then((r) => r.data)
  }
  const form = new FormData()
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined) form.append(key, String(value))
  }
  form.append('attachment', attachment)
  return apiClient
    .post<DebtPaymentResult>('/treasury-transactions/record-debt-payment/', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}

function buildAdvanceForm(fields: Record<string, unknown>, attachment: File): FormData {
  const form = new FormData()
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined && value !== null) form.append(key, String(value))
  }
  form.append('attachment', attachment)
  return form
}

export function createSupplierAdvance(payload: {
  supplier: number
  bank_account?: number | null
  cash_account?: number | null
  amount: string
  date: string
  reference?: string
  notes?: string
  attachment: File
}): Promise<SupplierAdvance> {
  const { attachment, ...fields } = payload
  return apiClient
    .post<SupplierAdvance>('/supplier-advances/', buildAdvanceForm(fields, attachment), {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}

export function createTransporterAdvance(payload: {
  transporter: number
  bank_account?: number | null
  cash_account?: number | null
  amount: string
  date: string
  reference?: string
  notes?: string
  attachment: File
}): Promise<TransporterAdvance> {
  const { attachment, ...fields } = payload
  return apiClient
    .post<TransporterAdvance>('/transporter-advances/', buildAdvanceForm(fields, attachment), {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}

// ControlledDebtPaymentService.describe_supplier_balance/describe_transporter_balance
// (backend/apps/finance/services.py) is the single source of truth for
// net_balance - never recompute it client-side.
export function fetchPartyBalances(partyType: PartyType): Promise<PartyBalance[]> {
  return apiClient
    .get<PartyBalance[]>('/treasury-transactions/party-balances/', {
      params: { debt_type: partyType },
    })
    .then((r) => r.data)
}

// --- Task 7 (client modifications plan): Shareholders / Associates -------

export const shareholderResource = createResourceApi<Shareholder>('/shareholders/')
export const shareholderLoanResource = createResourceApi<ShareholderLoan>('/shareholder-loans/')
export const shareholderWithdrawalResource = createResourceApi<ShareholderWithdrawal>(
  '/shareholder-withdrawals/',
)
export const shareholderDistributionResource = createResourceApi<ShareholderProfitDistribution>(
  '/shareholder-distributions/',
)

export function fetchShareholderLedger(shareholderId: number): Promise<ShareholderLedger> {
  return apiClient
    .get<ShareholderLedger>(`/shareholders/${shareholderId}/ledger/`)
    .then((r) => r.data)
}

// backend/apps/finance/services.py ShareholderProfitPreviewService.get_preview()
// Read-only, indicative current-profit split - never stored, never gates
// a withdrawal. `from`/`to` are optional; omitted, the backend defaults to
// the period since the last VALIDATED distribution (or all-time if none).
export function fetchShareholderProfitPreview(params?: {
  from?: string
  to?: string
}): Promise<ShareholderProfitPreview> {
  return apiClient
    .get<ShareholderProfitPreview>('/shareholders/profit-preview/', { params })
    .then((r) => r.data)
}

// backend/apps/finance/services.py ShareholderDistributionService.validate_distribution()
// is the sole authority on this transition (DRAFT -> VALIDATED, stamps
// validated_by/validated_at) - this just posts the request.
export function validateShareholderDistribution(
  distributionId: number,
): Promise<ShareholderProfitDistribution> {
  return apiClient
    .post<ShareholderProfitDistribution>(`/shareholder-distributions/${distributionId}/validate/`)
    .then((r) => r.data)
}

// backend/apps/finance/services.py ShareholderLoanService.record_repayment()
// is the sole authority on this write (Task 7 fix: loan-repayment
// lost-update race) - it increments amount_repaid under select_for_update()
// server-side, so this takes the INCREMENT amount, never a client-computed
// absolute total (amount_repaid is read-only on the plain update endpoint
// precisely to force every repayment through this atomic path).
export function recordShareholderLoanRepayment(
  loanId: number,
  amount: string,
): Promise<ShareholderLoan> {
  return apiClient
    .post<ShareholderLoan>(`/shareholder-loans/${loanId}/record-repayment/`, { amount })
    .then((r) => r.data)
}
