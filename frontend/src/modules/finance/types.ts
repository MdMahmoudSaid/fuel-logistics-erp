// Mirrors backend/apps/finance/serializers.py. DRF DecimalField values are
// all serialized as strings (never float) — convert with Number(...) only
// where arithmetic is needed, keep as strings for display/round-tripping.

import type { TruckBrief } from '@/modules/trips/types'

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
  // Recorded with "Nouvelle avance" - listed in the ledger's Avances section.
  is_advance?: boolean
  account_name?: string | null
  note: string
  recorded_by: number | null
  recorded_by_detail: UserBrief | null
  allocations?: InvoiceAllocationInput[]
  allocations_detail: PaymentAllocation[]
  unallocated_amount: string
  is_reversed: boolean
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
  // Task 6 (client business decision, confirmed 2026-09-06): set only by
  // SupplierPaymentCancellationService.cancel_supplier_payment via
  // POST /api/supplier-payments/{id}/cancel/ - never a plain edit.
  is_reversed: boolean
  created_at: string
  updated_at: string
}

export interface SupplierAdvance {
  id: number
  supplier: number
  supplier_detail: SupplierBrief | null
  bank_account: number | null
  cash_account: number | null
  amount: string
  date: string
  reference: string
  notes: string
  proof_url: string | null
  remaining_amount: string
  account_name?: string | null
  recorded_by: number | null
  created_at: string
  updated_at: string
}

// "Nouvelle dette" (2026-10-11): a debt from before the app, on a customer,
// supplier or transporter ledger. paid/remaining/status are server-derived.
export type OpeningDebtPartyType = 'customer' | 'supplier' | 'transporter'

export interface OpeningDebt {
  id: number
  customer: number | null
  supplier: number | null
  transporter: number | null
  party_type: OpeningDebtPartyType
  amount: string
  date: string
  reference: string
  notes: string
  proof_url: string | null
  paid_amount: string
  remaining_amount: string
  status: 'UNPAID' | 'PARTIALLY_PAID' | 'PAID' | 'CANCELLED'
  cancelled_at: string | null
  created_at: string
}

export interface TransporterAdvance {
  id: number
  transporter: number
  transporter_detail: TransporterBrief | null
  bank_account: number | null
  cash_account: number | null
  amount: string
  date: string
  reference: string
  notes: string
  proof_url: string | null
  remaining_amount: string
  settled: boolean
  account_name?: string | null
  created_at: string
  updated_at: string
}

export type TransportPaymentCalculationMethod = 'FIXED' | 'PER_LITRE' | 'PER_DAY' | 'NEGOTIATED'
export type TransportPaymentStatus =
  | 'PLANNED'
  | 'PAYABLE'
  | 'PARTIALLY_PAID'
  | 'PAID'
  | 'DEDUCTION_APPLIED'
  // Bug fix (2026-09-03 recette manuelle): set when the underlying Trip is
  // cancelled - see TransportPaymentCancellationService (backend).
  | 'CANCELLED'

export interface TransportPayment {
  can_modify?: boolean
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
  deduction_label?: string
  advance_applied: number | null
  net_amount: string
  status: TransportPaymentStatus
  created_at: string
  updated_at: string
}

export type ExpenseCategory =
  | 'customs'
  | 'import_intention'
  | 'transit'
  | 'road_transit'
  // 'transport' retired (transporter commission is the only transport-cost
  // channel) - kept in the union purely so legacy Expense rows still type.
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
  { value: 'transit', label: 'Transit' },
  { value: 'road_transit', label: 'Road transit' },
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

export interface ExpenseCategoryOption {
  id: number
  name: string
  code: string
  is_system: boolean
  is_active: boolean
  display_order: number
}

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
  category: string
  amount: string
  calculation_method: ExpenseCalculationMethod
  date: string
  status: ExpenseStatus
  paid_by_customer_directly: boolean
  // Who paid it: a customer (on our behalf), a bank or a cash account; null
  // while unpaid.
  paid_via?: 'customer' | 'bank' | 'cash' | null
  paid_via_name?: string | null
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
  'supplier' | 'transporter' | 'customs' | 'transit' | 'road_transit' | 'border' | 'loading'

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
  // Task 8: SaleSerializer now exposes the linked trip's loaded quantity
  // alongside the delivered quantity, so the ledger can show both per row.
  // subset of sales/types.ts Sale (the ledger only needs these two fields;
  // the full Sale interface carries customer/product detail this view never
  // reads).
  sale_detail?: {
    quantity_loaded: string
    delivered_quantity: string
    // Feedback (2026-09-10): "tractor / tanker" plates of the truck that
    // loaded this invoice's trip.
    truck_plates: string
  }
}

export interface CustomerLedger {
  customer: { id: number; name: string; company_name: string }
  outstanding_balance: string
  // Open customer credit (unallocated receipts), consumed by validated invoices.
  available_credit?: string
  invoices: CustomerLedgerInvoice[]
  opening_debts?: OpeningDebt[]
  payments: CustomerPayment[]
}

export interface TransporterLedger {
  transporter: { id: number; name: string; company_name: string }
  // Phase 6 (docs/superpowers/specs/2026-09-02-business-corrections-6-
  // phases-design.md): EXTERNAL trucks rattaches to this transporter -
  // a COMPANY_OWNED truck never appears here.
  trucks: TruckBrief[]
  gross_amount: string
  deductions: string
  advances_applied: string
  settled: string
  net_outstanding: string
  unsettled_advances: string
  payments: TransportPayment[]
  advances: TransporterAdvance[]
  opening_debts?: OpeningDebt[]
  summary: PartyBalance
  entries: LedgerEntry[]
}

// GET /api/treasury-transactions/party-balances/?debt_type=supplier|transporter
// (ControlledDebtPaymentService.describe_supplier_balance/
// describe_transporter_balance) - the single source of truth for net_balance,
// consumed as-is by AdvanceForm's party picker and (in a later wave) the
// Grand livre summary cards. Never recomputed client-side.
export type PartyType = 'supplier' | 'transporter'

export interface PartyBalance {
  id: number
  label: string
  total_due: string
  open_advances: string
  net_balance: string
  last_advance: { date: string; amount: string } | null
  last_payment: { date: string; amount: string } | null
}

// Wave 2: chronological Grand livre entries (SupplierLedgerService/
// TransporterLedgerService), returned alongside `summary` (same shape as
// PartyBalance) by GET /api/suppliers/{id}/ledger/ and
// GET /api/transporters/{id}/ledger/.
export type LedgerEntryType =
  'advance_given' | 'debt_created' | 'opening_debt' | 'advance_consumed' | 'payment'

export interface LedgerEntry {
  type: LedgerEntryType
  date: string
  amount: string
  reference: string
  note: string
  proof_url: string | null
}

// --- Task 7 (client modifications plan): Shareholders / Associates -------
// Mirrors backend/apps/finance/models.py's Shareholder* models and
// backend/apps/finance/serializers.py's Shareholder* serializers.

export interface ShareholderBrief {
  id: number
  name: string
  participation_percent: string
  contribution: string
}

export interface Shareholder {
  id: number
  name: string
  participation_percent: string
  contribution: string
  // Real cash injected via ShareholderContribution (Phase 1), distinct
  // from `contribution` above (a historical opening-balance figure set at
  // creation, never updated by a new apport). Annotated by
  // ShareholderViewSet, always present in list/detail responses.
  total_contributed: string
  phone: string
  notes: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export type ShareholderDistributionStatus = 'DRAFT' | 'VALIDATED' | 'CANCELLED'

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
  // DRAFT only: the profit still left to distribute (what "Valider" is
  // checked against by the backend); null once validated/cancelled.
  available_to_distribute?: string | null
  created_by: number | null
  created_by_detail: UserBrief | null
  validated_by: number | null
  validated_by_detail: UserBrief | null
  validated_at: string | null
  cancelled_by: number | null
  cancelled_by_detail: UserBrief | null
  cancelled_at: string | null
  shares: ShareholderProfitShare[]
  created_at: string
  updated_at: string
}

export type ShareholderProfitPeriodStatus = 'OPEN' | 'CLOSED'

export interface ShareholderProfitPeriod {
  id: number
  start_date: string
  end_date: string | null
  status: ShareholderProfitPeriodStatus
  net_profit: string | null
  live_net_profit: string | null
  preview_end_date: string | null
  distribution: number | null
  distribution_detail: ShareholderProfitDistribution | null
  opened_by: number
  opened_by_detail: UserBrief | null
  closed_by: number | null
  closed_by_detail: UserBrief | null
  closed_at: string | null
  reopened_by: number | null
  reopened_by_detail: UserBrief | null
  reopened_at: string | null
  reopen_reason: string
  reopen_count: number
  created_at: string
  updated_at: string
}

export type ShareholderLoanStatus = 'OPEN' | 'PARTIALLY_REPAID' | 'REPAID'

// Client request 2026-10-11: an advance comes from another associate
// (SHAREHOLDER, no treasury movement) or from the company treasury
// (COMPANY, deducted from the borrower's next validated profit share).
export type ShareholderLoanSource = 'SHAREHOLDER' | 'COMPANY'
export type ShareholderLoanRepaymentMethod = 'DIRECT' | 'TREASURY' | 'PROFIT_SHARE' | 'CANCEL'

export interface ShareholderLoanRepayment {
  id: number
  method: ShareholderLoanRepaymentMethod
  amount: string
  date: string
  account_name: string | null
  distribution_period: string | null
  notes: string
}

export interface ShareholderLoan {
  id: number
  source: ShareholderLoanSource
  borrower: number
  borrower_detail: ShareholderBrief | null
  lender: number | null
  lender_detail: ShareholderBrief | null
  amount: string
  date: string
  status: ShareholderLoanStatus
  amount_repaid: string
  remaining_amount: string
  // COMPANY only: withdrawn so far, cancelled before any withdrawal, still
  // withdrawable, and cash really out and still owed (the most a treasury
  // repayment may bring back).
  amount_drawn: string
  amount_cancelled: string
  undrawn_amount: string
  cash_outstanding: string
  notes: string
  repayments: ShareholderLoanRepayment[]
  created_at: string
  updated_at: string
}

export interface ShareholderWithdrawalAllocation {
  profit_share: number | null
  contribution: number | null
  advance?: number | null
  amount: string
}

export interface ShareholderWithdrawal {
  id: number
  shareholder: number
  shareholder_detail: ShareholderBrief | null
  allocations: ShareholderWithdrawalAllocation[]
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

export interface ShareholderContribution {
  id: number
  shareholder: number
  shareholder_detail: ShareholderBrief | null
  amount: string
  amount_returned: string
  remaining_capital: string
  date: string
  bank_account: number | null
  cash_account: number | null
  reference: string
  notes: string
  proof_url: string | null
  is_cancelled?: boolean
  cancelled_at?: string | null
  cancel_reason?: string
  // Why this apport can no longer be cancelled / re-assigned (null = free).
  blocked_reason?: string | null
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
  source: ShareholderLoanSource
  amount_drawn: string
  undrawn_amount: string
  amount: string
  amount_repaid: string
  remaining_amount: string
  status: ShareholderLoanStatus
  date: string
  notes: string
  repayments: ShareholderLoanRepayment[]
  lender_id?: number | null
  lender_name?: string | null
  borrower_id?: number
  borrower_name?: string
}

export interface ShareholderLedgerWithdrawal {
  id: number
  amount: string
  date: string
  allocations: ShareholderWithdrawalAllocation[]
  bank_account_id: number | null
  cash_account_id: number | null
  notes: string
}

export interface ShareholderLedger {
  shareholder: {
    id: number
    name: string
    participation_percent: string
    contribution?: string
    is_active: boolean
  }
  total_amount_due: string
  total_withdrawn: string
  remaining_due: string
  // ShareholderLedgerService.get_available_balance(): remaining_due +
  // capital_remaining + loans given (as lender, still receivable) - loans
  // received (as borrower, a liability) - the single number that gates
  // both a withdrawal and lending money to another associate.
  available_balance: string
  // Real cash injected via ShareholderContribution, gross/historical -
  // never decreases even once some of it is returned via a withdrawal.
  total_contributed: string
  // Sum of ShareholderContribution.amount_returned across all of this
  // shareholder's contributions.
  capital_returned: string
  // total_contributed - capital_returned - the part of available_balance
  // that comes from capital rather than profit.
  capital_remaining: string
  shares: ShareholderLedgerShare[]
  loans_borrowed: ShareholderLedgerLoan[]
  loans_lent: ShareholderLedgerLoan[]
  net_loan_balance: string
  // Outstanding company advances (deducted from the next profit share),
  // what he owes other associates, and what they owe him.
  company_advance_debt: string
  // Company advances granted and not yet withdrawn, and what he can
  // withdraw now (balance + company advance still owed).
  company_advance_undrawn: string
  withdrawable_balance: string
  shareholder_loan_debt: string
  shareholder_loan_receivable: string
  withdrawals: ShareholderLedgerWithdrawal[]
}

// GET /api/shareholders/balances/ (ShareholderLedgerService.get_balances_summary)
// Real, comptable balance per active shareholder - the same figure as the
// Grand livre tab's "solde disponible" - summed across all of them. Client
// request (2026-09-16): distinct from ShareholderProfitPreview below, which
// is only an indicative/forecast distribution figure.
export interface ShareholderBalanceRow {
  id: number
  name: string
  available_balance: string
}

export interface ShareholderBalancesSummary {
  shareholders: ShareholderBalanceRow[]
  total: string
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

// "Fond de roulement client" (docs/superpowers/specs/2026-09-04-recette-
// corrections-design.md, Section 3) - WorkingCapitalService.get_working_capital()
// (backend/apps/finance/services.py). A management indicator, NOT the
// accounting fonds de roulement. Confirmed via actual client recette
// testing (third pass, 2026-09-04): open debts are ADDED, not subtracted -
// gross = treasury_available + customer_receivables; total = gross +
// supplier_debt_total + transporter_debt_total + other_debts +
// supplier_reliquat_value. Capital is informational only, not part of
// gross/total (only subtracted separately to reach distributable_result).
export interface WorkingCapital {
  capital: string
  treasury_available: string
  customer_receivables: string
  supplier_debt_total: string
  transporter_debt_total: string
  other_debts: string
  shareholder_dues: string
  supplier_reliquat_value: string
  supplier_in_transit_value: string
  supplier_company_stock_value: string
  gross: string
  total: string
}

export interface ShareholderProfitPreview {
  period_start: string | null
  period_end: string | null
  current_profit: string
  // Phase 4 (docs/superpowers/specs/2026-09-02-business-corrections-6-
  // phases-design.md): operational_profit is trips-only (same value as
  // current_profit); net_profit = operational_profit - general_expenses_paid
  // (unallocated Expense rows actually PAID in the period).
  operational_profit: string
  // Sum of the margin-report rows' revenue for the same scope.
  revenue: string
  general_expenses_paid: string
  // "Periode en cours" reconciliation (spec 2026-10-05-periodes-
  // independantes): operational_profit - general_expenses_paid +
  // carried_over - distributions_since_closure == distributable_result.
  // Both are "0.00" for any other date filter.
  carried_over: string
  distributions_since_closure: string
  net_profit: string
  // Tolerance-absorbed delivery loss (DeliveryControl.company_absorbed_
  // loss_quantity x unit_selling_price), summed across every trip. Already
  // subtracted from distributable_result below - surfaced here so the
  // Distribution breakdown can show it as an explicit line rather than an
  // invisible gap (recette 2026-09-07).
  total_company_absorbed_loss: string
  // Client modifications (2026-09-04): "Resultat distribuable apres dettes
  // et capital" replaces the old total_capital_contributed/profit_after_capital
  // pair entirely - informational only, never feeds indicative_share (still
  // net_profit-based) or a distribution's total_profit.
  working_capital: WorkingCapital
  // Sum of amount_due - amount_withdrawn across every non-cancelled
  // ShareholderProfitShare, company-wide (recette fix, 2026-09-08):
  // money already committed to shareholders via an earlier distribution,
  // even if not yet withdrawn - already subtracted into
  // distributable_result below, surfaced here so the distribution form
  // can show "deja reparti" / "reste a repartir" explicitly instead of a
  // figure that silently never moves.
  already_distributed: string
  // 2026-09-25: distributable_result = all_time_net_profit -
  // already_validated_total (every VALIDATED distribution), whatever period
  // is previewed; result_after_debts_and_capital is kept for information only.
  all_time_net_profit: string
  already_validated_total: string
  result_after_debts_and_capital: string
  distributable_result: string
  shareholders: ShareholderProfitPreviewShare[]
}

// GET /api/dashboard/financial-position/ (backend apps/reports/services/
// financial_position.py): what the company owns vs what it owes, and the net
// result = owned - owed. Amounts are decimal strings.
export interface FinancialPositionChild {
  // Either a data label (an account / associate name) or a translatable key.
  label?: string
  key?: string
  amount: string
}

export interface FinancialPositionLine {
  key: string
  amount: string
  children: FinancialPositionChild[]
}

export interface FinancialPositionSide {
  lines: FinancialPositionLine[]
  total: string
}

export interface FinancialPosition {
  assets: FinancialPositionSide
  liabilities: FinancialPositionSide
  net_result: string
  // Control: the net result must equal the distributable net profit.
  distributable_result: string
  gap: string
  // Open debts matched by fuel / costs not sold yet (shown on neither side).
  matched_unsold: string
  capital: string
}
