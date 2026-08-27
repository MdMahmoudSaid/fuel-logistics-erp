// Mirrors backend/apps/finance/serializers.py. DRF DecimalField values are
// all serialized as strings (never float) — convert with Number(...) only
// where arithmetic is needed, keep as strings for display/round-tripping.

export interface CustomerBrief {
  id: number
  name: string
  company_name: string
}

export interface SupplierBrief {
  id: number
  name: string
  company_name: string
  country: string
}

export interface TransporterBrief {
  id: number
  name: string
  company_name: string
}

export interface UserBrief {
  id: number
  email: string
  full_name: string
}

export type PaymentMethod = 'CASH' | 'BANK_TRANSFER' | 'CHEQUE' | 'OTHER'

// Mirrors CustomerPayment.Destination (backend/apps/finance/models.py).
// `destination` is the single source of truth CustomerPaymentSerializer.
// validate() derives is_indirect/bank_account/cash_account from - the
// client only ever needs to send this (plus the matching account for
// BANK/CASH) rather than getting is_indirect/account fields consistent
// itself.
export type CustomerPaymentDestination = 'BANK' | 'CASH' | 'VERS_MOI' | 'INDIRECT'

export interface PaymentAllocation {
  id: number
  payment: number
  invoice: number | null
  invoice_number: string | null
  amount: string
  created_at: string
}

// Write-only shape accepted by CustomerPaymentSerializer/ExpenseSerializer's
// nested `allocations` field (backend/apps/finance/serializers.py).
export interface InvoiceAllocationInput {
  invoice: number | null
  amount: string
}

export interface CustomerPayment {
  id: number
  customer: number
  customer_detail: CustomerBrief | null
  amount: string
  payment_date: string
  method: PaymentMethod
  bank_account: number | null
  cash_account: number | null
  reference: string
  is_indirect: boolean
  destination: CustomerPaymentDestination
  note: string
  recorded_by: number | null
  recorded_by_detail: UserBrief | null
  allocations?: InvoiceAllocationInput[]
  allocations_detail: PaymentAllocation[]
  proof_url: string | null
  created_at: string
  updated_at: string
}

export interface SupplierPayment {
  id: number
  supplier: number
  supplier_detail: SupplierBrief | null
  supplier_order: number | null
  amount: string
  payment_date: string
  method: PaymentMethod
  bank_account: number | null
  cash_account: number | null
  is_advance: boolean
  reference: string
  recorded_by: number | null
  recorded_by_detail: UserBrief | null
  created_at: string
  updated_at: string
}

export interface TransporterAdvance {
  id: number
  transporter: number
  transporter_detail: TransporterBrief | null
  amount: string
  date: string
  reference: string
  notes: string
  settled: boolean
  created_at: string
  updated_at: string
}

export type TransportPaymentCalculationMethod = 'FIXED' | 'PER_LITRE' | 'PER_DAY' | 'NEGOTIATED'
export type TransportPaymentStatus =
  'PLANNED' | 'PAYABLE' | 'PARTIALLY_PAID' | 'PAID' | 'DEDUCTION_APPLIED'

export interface TransportPayment {
  id: number
  trip: number
  trip_reference: string
  transporter: number
  transporter_detail: TransporterBrief | null
  calculation_method: TransportPaymentCalculationMethod
  base_amount: string
  // Only set (and required) when calculation_method is PER_LITRE - the
  // backend derives base_amount from trip.quantity_loaded * this value and
  // rejects a client-supplied base_amount for that method (backend/apps/
  // finance/serializers.py TransportPaymentSerializer.validate()).
  unit_price_per_litre: string | null
  deduction_amount: string
  advance_applied: number | null
  net_amount: string
  status: TransportPaymentStatus
  created_at: string
  updated_at: string
}

export type ExpenseCategory =
  | 'customs'
  | 'import_intention'
  | 'transport'
  | 'loading'
  | 'unloading'
  | 'road'
  | 'administration'
  | 'rent'
  | 'salary'
  | 'repairs'
  | 'bank_charges'
  | 'other'

export const EXPENSE_CATEGORIES: { value: ExpenseCategory; label: string }[] = [
  { value: 'customs', label: 'Customs' },
  { value: 'import_intention', label: 'Import intention' },
  { value: 'transport', label: 'Transport' },
  { value: 'loading', label: 'Loading' },
  { value: 'unloading', label: 'Unloading' },
  { value: 'road', label: 'Road' },
  { value: 'administration', label: 'Administration' },
  { value: 'rent', label: 'Rent' },
  { value: 'salary', label: 'Salary' },
  { value: 'repairs', label: 'Repairs' },
  { value: 'bank_charges', label: 'Bank charges' },
  { value: 'other', label: 'Other' },
]

export type ExpenseCalculationMethod =
  'FIXED' | 'PER_LITRE' | 'PERCENTAGE' | 'PER_ORDER' | 'PER_TRUCK' | 'MANUAL'

export type ExpenseStatus = 'UNPAID' | 'PARTIALLY_PAID' | 'PAID' | 'CANCELLED'

export interface ExpenseAllocation {
  id: number
  expense: number
  content_type: number | null
  content_type_name: string | null
  object_id: number | null
  content_object_repr: string
  allocated_amount: string
  created_at: string
}

export interface ExpenseAllocationInput {
  content_type?: number | null
  object_id?: number | null
  allocated_amount: string
}

// Mirrors backend/apps/finance/views.py's _ALLOCATABLE_KINDS - the entity
// kinds an ExpenseAllocation can point at (guide Section 8.7: "split across
// several trips, trucks, customers, suppliers or transporters"). Matches
// the array keys GET /search/ returns them under, so a picked kind can
// index straight into a SearchResults response.
export type AllocatableKind = 'trip' | 'truck' | 'customer' | 'supplier' | 'transporter'

export const ALLOCATABLE_KINDS: AllocatableKind[] = [
  'trip',
  'truck',
  'customer',
  'supplier',
  'transporter',
]

// GET /api/allocatable-types/ - kind -> ContentType PK, the only way the
// frontend can resolve a human choice ("Trip") to the numeric content_type
// ExpenseAllocationInputSerializer expects.
export type AllocatableTypeMap = Partial<Record<AllocatableKind, number>>

export interface Expense {
  id: number
  category: ExpenseCategory
  amount: string
  calculation_method: ExpenseCalculationMethod
  date: string
  status: ExpenseStatus
  paid_by_customer_directly: boolean
  notes: string
  allocations?: ExpenseAllocationInput[]
  allocations_detail: ExpenseAllocation[]
  created_at: string
  updated_at: string
}

export type TreasuryTransactionType = 'MONEY_IN' | 'MONEY_OUT'

export interface TreasuryTransaction {
  id: number
  bank_account: number | null
  bank_account_name: string | null
  cash_account: number | null
  cash_account_name: string | null
  type: TreasuryTransactionType
  // Set only by TreasuryService.record_transfer() - both legs of an
  // internal transfer carry this instead of a dedicated `type` value, so
  // current_balance can still sum plain MONEY_IN/MONEY_OUT unambiguously.
  is_transfer: boolean
  amount: string
  date: string
  reference: string
  note: string
  // Human "source ou beneficiaire" label resolved server-side (e.g.
  // "Fournisseur - Ahmed", "Douane", "Transfert Banque BOA -> Caisse
  // Recette") - see backend/apps/finance/labels.py.
  counterparty: string | null
  source_content_type: number | null
  source_object_id: number | null
  source_object_repr: string
  document: number | null
  document_url: string | null
  recorded_by: number | null
  recorded_by_detail: UserBrief | null
  created_at: string
  updated_at: string
}

export type DebtPaymentType =
  'supplier' | 'transporter' | 'customs' | 'transit' | 'border' | 'loading' | 'trip_other'

export interface PayableDebt {
  id: number
  debt_type: DebtPaymentType
  label: string
  total_amount: string
  paid_amount: string
  remaining_amount: string
  status: string
  lines?: PayableDebt[]
}

export interface DebtPaymentResult {
  transaction: TreasuryTransaction | null
  transactions: TreasuryTransaction[]
  debt: PayableDebt
  bank_balance_before: string
  bank_balance_after: string
}

export interface CustomerLedgerInvoice {
  id: number
  invoice_number: string
  status: string
  total_amount: string
  issued_date: string
  // Annotated by GET /api/customers/{id}/ledger/ on top of InvoiceSerializer
  // via PaymentAllocationService.get_invoice_outstanding() - not present on
  // the plain Invoice resource itself.
  outstanding: string
}

export interface CustomerLedger {
  customer: { id: number; name: string; company_name: string }
  outstanding_balance: string
  invoices: CustomerLedgerInvoice[]
  payments: CustomerPayment[]
}

export interface TransporterLedger {
  transporter: { id: number; name: string; company_name: string }
  gross_amount: string
  deductions: string
  advances_applied: string
  settled: string
  net_outstanding: string
  unsettled_advances: string
  payments: TransportPayment[]
  advances: TransporterAdvance[]
}

// --- Task 7 (client modifications plan): Shareholders / Associates -------
// Mirrors backend/apps/finance/models.py's Shareholder* models and
// backend/apps/finance/serializers.py's Shareholder* serializers.

export interface ShareholderBrief {
  id: number
  name: string
  participation_percent: string
}

export interface Shareholder {
  id: number
  name: string
  participation_percent: string
  phone: string
  notes: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export type ShareholderDistributionStatus = 'DRAFT' | 'VALIDATED'

export interface ShareholderProfitShare {
  id: number
  distribution: number
  shareholder: number
  shareholder_detail: ShareholderBrief | null
  percent_snapshot: string
  amount_due: string
  amount_withdrawn: string
  remaining_due: string
  created_at: string
  updated_at: string
}

export interface ShareholderProfitDistribution {
  id: number
  period_start: string
  period_end: string
  total_profit: string
  status: ShareholderDistributionStatus
  created_by: number | null
  created_by_detail: UserBrief | null
  validated_by: number | null
  validated_by_detail: UserBrief | null
  validated_at: string | null
  shares: ShareholderProfitShare[]
  created_at: string
  updated_at: string
}

export type ShareholderLoanStatus = 'OPEN' | 'PARTIALLY_REPAID' | 'REPAID'

export interface ShareholderLoan {
  id: number
  borrower: number
  borrower_detail: ShareholderBrief | null
  lender: number
  lender_detail: ShareholderBrief | null
  amount: string
  date: string
  status: ShareholderLoanStatus
  amount_repaid: string
  remaining_amount: string
  notes: string
  created_at: string
  updated_at: string
}

export interface ShareholderWithdrawal {
  id: number
  shareholder: number
  shareholder_detail: ShareholderBrief | null
  profit_share: number | null
  amount: string
  date: string
  bank_account: number | null
  cash_account: number | null
  notes: string
  recorded_by: number | null
  recorded_by_detail: UserBrief | null
  created_at: string
  updated_at: string
}

// GET /api/shareholders/{id}/ledger/ (ShareholderLedgerService.get_shareholder_summary)
export interface ShareholderLedgerShare {
  id: number
  distribution_id: number
  period_start: string
  period_end: string
  percent_snapshot: string
  amount_due: string
  amount_withdrawn: string
  remaining_due: string
}

export interface ShareholderLedgerLoan {
  id: number
  amount: string
  amount_repaid: string
  remaining_amount: string
  status: ShareholderLoanStatus
  date: string
  lender_id?: number
  lender_name?: string
  borrower_id?: number
  borrower_name?: string
}

export interface ShareholderLedgerWithdrawal {
  id: number
  amount: string
  date: string
  profit_share_id: number | null
  bank_account_id: number | null
  cash_account_id: number | null
  notes: string
}

export interface ShareholderLedger {
  shareholder: { id: number; name: string; participation_percent: string; is_active: boolean }
  total_amount_due: string
  total_withdrawn: string
  remaining_due: string
  // ShareholderLedgerService.get_available_balance(): remaining_due +
  // loans given (as lender, still receivable) - loans received (as
  // borrower, a liability) - the single number that gates both a
  // withdrawal and lending money to another associate.
  available_balance: string
  shares: ShareholderLedgerShare[]
  loans_borrowed: ShareholderLedgerLoan[]
  loans_lent: ShareholderLedgerLoan[]
  net_loan_balance: string
  withdrawals: ShareholderLedgerWithdrawal[]
}

// GET /api/shareholders/profit-preview/ (ShareholderProfitPreviewService.get_preview)
// Read-only and indicative only - never a stored figure, never affects
// available_balance or withdrawal eligibility.
export interface ShareholderProfitPreviewShare {
  shareholder_id: number
  name: string
  participation_percent: string
  indicative_share: string
}

export interface ShareholderProfitPreview {
  period_start: string | null
  period_end: string | null
  current_profit: string
  shareholders: ShareholderProfitPreviewShare[]
}
