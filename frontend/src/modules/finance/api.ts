import { apiClient } from '@/api/client'
import { createResourceApi } from '@/api/resource'
import type {
  CustomerLedger,
  CustomerPayment,
  Expense,
  SupplierPayment,
  TransporterAdvance,
  TransporterLedger,
  TransportPayment,
  TreasuryTransaction,
} from './types'

export const customerPaymentResource = createResourceApi<CustomerPayment>('/customer-payments/')
export const supplierPaymentResource = createResourceApi<SupplierPayment>('/supplier-payments/')
export const transporterAdvanceResource =
  createResourceApi<TransporterAdvance>('/transporter-advances/')
export const transportPaymentResource = createResourceApi<TransportPayment>('/transport-payments/')
export const expenseResource = createResourceApi<Expense>('/expenses/')
export const treasuryTransactionResource =
  createResourceApi<TreasuryTransaction>('/treasury-transactions/')

export function fetchCustomerLedger(customerId: number): Promise<CustomerLedger> {
  return apiClient.get<CustomerLedger>(`/customers/${customerId}/ledger/`).then((r) => r.data)
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
