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
  ExpenseCategoryOption,
  PartyBalance,
  PartyType,
  Shareholder,
  ShareholderBalancesSummary,
  ShareholderContribution,
  ShareholderLedger,
  ShareholderLoan,
  ShareholderProfitDistribution,
  ShareholderProfitPeriod,
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
export const expenseCategoryResource =
  createResourceApi<ExpenseCategoryOption>('/expense-categories/')

export function createExpenseCategory(payload: { name: string }): Promise<ExpenseCategoryOption> {
  return apiClient.post<ExpenseCategoryOption>('/expense-categories/', payload).then((r) => r.data)
}

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

export function allocateExistingCustomerPayment(
  paymentId: number,
  allocations: { invoice: number; amount: string }[],
): Promise<CustomerPayment> {
  return apiClient
    .post<CustomerPayment>(`/customer-payments/${paymentId}/allocate/`, { allocations })
    .then((r) => r.data)
}

// Task 10/11 PDF exports - dedicated `/ledger/pdf/` actions rather than
// `?format=pdf`: DRF's DefaultContentNegotiation reserves the `format`
// query param for its own renderer selection (backend/apps/suppliers/
// views.py SupplierViewSet.ledger_pdf docstring). Mirrors
// modules/reports/api.ts's downloadReportExport blob-download pattern.
const LEDGER_PDF_PATH: Record<'supplier' | 'transporter' | 'customer', string> = {
  supplier: 'suppliers',
  transporter: 'transporters',
  customer: 'customers',
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

export async function exportLedgerPdf(
  kind: 'supplier' | 'transporter' | 'customer',
  id: number,
  lang: string,
): Promise<void> {
  const response = await apiClient.get(`/${LEDGER_PDF_PATH[kind]}/${id}/ledger/pdf/`, {
    params: { lang },
    responseType: 'blob',
  })
  downloadBlob(new Blob([response.data]), `${kind}-ledger-${id}.pdf`)
}

// GET /api/transport-payments/{id}/pdf/?lang=fr|en|ar (backend/apps/
// finance/views.py TransportPaymentViewSet.pdf) - per-trip "Reglement par
// trajet" settlement PDF, Task 11.
export async function exportTransportPaymentPdf(id: number, lang: string): Promise<void> {
  const response = await apiClient.get(`/transport-payments/${id}/pdf/`, {
    params: { lang },
    responseType: 'blob',
  })
  downloadBlob(new Blob([response.data]), `reglement-${id}.pdf`)
}

// Recette corrections (2026-09-05): Grand livre client/fournisseur now
// have the same per-payment PDF action Grand livre transporteur already
// had (GET /api/customer-payments/{id}/pdf/, /api/supplier-payments/{id}/
// pdf/ - backend/apps/finance/views.py CustomerPaymentViewSet.pdf /
// SupplierPaymentViewSet.pdf).
export async function exportCustomerPaymentPdf(id: number, lang: string): Promise<void> {
  const response = await apiClient.get(`/customer-payments/${id}/pdf/`, {
    params: { lang },
    responseType: 'blob',
  })
  downloadBlob(new Blob([response.data]), `paiement-client-${id}.pdf`)
}

export async function exportSupplierPaymentPdf(id: number, lang: string): Promise<void> {
  const response = await apiClient.get(`/supplier-payments/${id}/pdf/`, {
    params: { lang },
    responseType: 'blob',
  })
  downloadBlob(new Blob([response.data]), `paiement-fournisseur-${id}.pdf`)
}

// GET /api/shareholders/profit-preview/pdf/?from=&to=&lang= (client
// request 2026-09-06, backend/apps/finance/views.py ShareholderViewSet.
// profit_preview_pdf) - full "Benefices" page export (profitability, the
// complete fond-de-roulement breakdown, and the per-trip detail table),
// respecting the same period filter as the page's own DateRangeFilter.
export async function exportProfitReportPdf(
  dateRangeParams: Record<string, string | undefined>,
  lang: string,
): Promise<void> {
  const response = await apiClient.get('/shareholders/profit-preview/pdf/', {
    params: { ...dateRangeParams, lang },
    responseType: 'blob',
  })
  downloadBlob(new Blob([response.data]), 'rapport-benefices.pdf')
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
  // Bug fix (found during 2026-09-06 manual recette): proof is optional on
  // customer payments (backend CustomerPaymentSerializer.validate_proof
  // already accepts None) - was typed as a required File, so a null/
  // undefined caller value would have been coerced to the literal string
  // "null" by FormData.append below instead of being omitted.
  proof?: File | null,
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
  if (proof) {
    form.append('proof', proof)
  }
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

// General expense paid by one or several customers on the company's behalf
// (client request 2026-09-25): each payer's amount comes off what he owes,
// or becomes a company debt towards him once he owes nothing - backend
// IndirectSettlementService.record_customer_paid_expenses().
export function recordCustomerPaidExpenses(payload: {
  category: string
  date: string
  notes?: string
  payers: { customer: number; amount: string }[]
}): Promise<{ expenses: Expense[] }> {
  return apiClient
    .post('/expenses/record-customer-paid/', payload)
    .then((r) => r.data as { expenses: Expense[] })
}

// backend/apps/finance/services.py ExpensePostingService.cancel_paid_expense()
// is the sole authority on this flow (Phase 5) - this just posts the request.
export function cancelExpense(expenseId: number): Promise<Expense> {
  return apiClient.post(`/expenses/${expenseId}/cancel/`).then((r) => r.data as Expense)
}

// backend/apps/finance/services.py TransportPaymentCancellationService.
// cancel_transport_payment() is the sole authority on this flow (bug fix,
// 2026-09-17: the frontend never exposed a way to reverse a settled
// "Commission transporteur" the way it already does for other trip fees)
// - this just posts the request.
export function cancelTransportPayment(paymentId: number): Promise<TransportPayment> {
  return apiClient
    .post(`/transport-payments/${paymentId}/cancel/`)
    .then((r) => r.data as TransportPayment)
}

// backend/apps/finance/services.py TransportPaymentCorrectionService.
// correct_payment() is the sole authority on this flow: corrects a settled
// commission's rate/amount in place (e.g. a wrong per-litre rate found
// after payment) without a cancel-then-recreate cycle. A trop-percu never
// triggers a cash clawback - it silently caps future payouts to that
// transporter instead (client discussion 2026-09-17).
export function correctTransportPayment(
  paymentId: number,
  payload: { base_amount?: string; unit_price_per_litre?: string; reason?: string },
): Promise<TransportPayment> {
  return apiClient
    .post(`/transport-payments/${paymentId}/correct/`, payload)
    .then((r) => r.data as TransportPayment)
}

// backend/apps/finance/services.py SupplierPaymentCancellationService.
// cancel_supplier_payment() is the sole authority on this flow (Task 6,
// client business decision confirmed 2026-09-06) - this just posts the
// request. A SupplierPayment can never be edited or hard-deleted past
// creation, so this contre-passation is the only way to correct one.
export function cancelSupplierPayment(paymentId: number): Promise<SupplierPayment> {
  return apiClient
    .post(`/supplier-payments/${paymentId}/cancel/`)
    .then((r) => r.data as SupplierPayment)
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
  surplus_as_advance?: boolean
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

// Task 14 (client modifications, 2026-09-04): proof upload is no longer
// required on advances/contributions - backend already accepts these flows
// without an attachment (Section 6). `attachment` stays optional here;
// omitted entirely from the FormData when null/undefined rather than
// appending a stringified "null".
function buildAdvanceForm(fields: Record<string, unknown>, attachment?: File | null): FormData {
  const form = new FormData()
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined && value !== null) form.append(key, String(value))
  }
  if (attachment) form.append('attachment', attachment)
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
  attachment?: File | null
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
  attachment?: File | null
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
export const shareholderContributionResource = createResourceApi<ShareholderContribution>(
  '/shareholder-contributions/',
)
export const shareholderDistributionResource = createResourceApi<ShareholderProfitDistribution>(
  '/shareholder-distributions/',
)
export const shareholderProfitPeriodResource =
  createResourceApi<ShareholderProfitPeriod>('/shareholder-periods/')

export function closeShareholderProfitPeriod(
  periodId: number,
  endDate: string,
): Promise<ShareholderProfitPeriod> {
  return apiClient
    .post<ShareholderProfitPeriod>(`/shareholder-periods/${periodId}/close/`, {
      end_date: endDate,
    })
    .then((r) => r.data)
}

export function reopenShareholderProfitPeriod(
  periodId: number,
  reason: string,
): Promise<ShareholderProfitPeriod> {
  return apiClient
    .post<ShareholderProfitPeriod>(`/shareholder-periods/${periodId}/reopen/`, { reason })
    .then((r) => r.data)
}

export function createShareholderContribution(payload: {
  shareholder: number
  bank_account?: number | null
  cash_account?: number | null
  amount: string
  date: string
  reference?: string
  notes?: string
  attachment?: File | null
}): Promise<ShareholderContribution> {
  const { attachment, ...fields } = payload
  return apiClient
    .post<ShareholderContribution>(
      '/shareholder-contributions/',
      buildAdvanceForm(fields, attachment),
      {
        headers: { 'Content-Type': 'multipart/form-data' },
      },
    )
    .then((r) => r.data)
}

export function fetchShareholderLedger(shareholderId: number): Promise<ShareholderLedger> {
  return apiClient
    .get<ShareholderLedger>(`/shareholders/${shareholderId}/ledger/`)
    .then((r) => r.data)
}

// backend/apps/finance/services.py ShareholderLedgerService.get_balances_summary()
// Real, comptable balance per active shareholder (same figure as the Grand
// livre tab's "solde disponible"), summed - distinct from the indicative
// profit-preview figures below.
export function fetchShareholderBalancesSummary(): Promise<ShareholderBalancesSummary> {
  return apiClient.get<ShareholderBalancesSummary>('/shareholders/balances/').then((r) => r.data)
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

// backend/apps/finance/services.py ShareholderDistributionService.cancel_distribution()
// is the sole authority on this transition (DRAFT/VALIDATED -> CANCELLED,
// stamps cancelled_by/cancelled_at, refuses if a withdrawal already
// exists against one of the distribution's shares) - this just posts the
// request.
export function cancelShareholderDistribution(
  distributionId: number,
): Promise<ShareholderProfitDistribution> {
  return apiClient
    .post<ShareholderProfitDistribution>(`/shareholder-distributions/${distributionId}/cancel/`)
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
