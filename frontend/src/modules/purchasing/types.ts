// Mirrors backend/apps/purchasing/serializers.py and
// backend/apps/documents/serializers.py. DRF DecimalField / computed
// SerializerMethodField quantities are all serialized as strings (never
// float) — convert with Number(...) only where arithmetic is needed, keep
// as strings for display/round-tripping into forms.

import type { LedgerEntry, PartyBalance } from '@/modules/finance/types'

export interface SupplierBrief {
  id: number
  name: string
  company_name: string
  country: string
}

export interface ProductBrief {
  id: number
  name: string
  code: string
}

export interface UserBrief {
  id: number
  email: string
  full_name: string
}

export interface DocumentRecord {
  id: number
  file: string
  document_type: string
  reference: string
  uploaded_by: number
  uploaded_by_email: string
  created_at: string
}

export type SupplierOrderStatus = 'DRAFT' | 'CONFIRMED' | 'CANCELLED'
export type CessionLetterStatus = 'ACTIVE' | 'EXHAUSTED' | 'CANCELLED'

export interface CessionLetter {
  id: number
  reference: string
  supplier_order: number
  authorized_quantity: string
  issue_date: string
  status: CessionLetterStatus
  notes: string
  created_by: number | null
  created_by_detail: UserBrief | null
  loaded_quantity: string
  remaining_quantity: string
  documents: DocumentRecord[]
  created_at: string
  updated_at: string
}

export interface SupplierOrder {
  id: number
  reference: string
  supplier: number
  supplier_detail: SupplierBrief | null
  product: number
  product_detail: ProductBrief | null
  purchase_date: string
  quantity_litres: string
  unit_price: string
  currency: string
  total_amount: string
  optional_costs: string | null
  notes: string
  status: SupplierOrderStatus
  created_by: number | null
  created_by_detail: UserBrief | null
  reliquat: string
  loaded_quantity: string
  documents: DocumentRecord[]
  cessions: CessionLetter[]
  created_at: string
  updated_at: string
}

export interface SupplierLedgerProductReliquat {
  product_id: number
  product_name: string
  total_reliquat: string
}

// backend/apps/finance/serializers.py SupplierPaymentSerializer - imported
// as a loose subset here rather than from apps/finance/types.ts to avoid a
// module cycle (finance/types already models the reverse relation).
export interface SupplierLedgerPayment {
  id: number
  amount: string
  payment_date: string
  method: string
  is_advance: boolean
  reference: string
  proof_url: string | null
  // Task 6 (client business decision, confirmed 2026-09-06): set only by
  // SupplierPaymentCancellationService.cancel_supplier_payment via
  // POST /api/supplier-payments/{id}/cancel/ - never a plain edit.
  is_reversed: boolean
}

export interface SupplierLedger {
  supplier: { id: number; name: string }
  orders: SupplierOrder[]
  reliquat_summary: SupplierLedgerProductReliquat[]
  payments: SupplierLedgerPayment[]
  total_purchased: string
  total_paid: string
  outstanding_balance: string
  summary: PartyBalance
  entries: LedgerEntry[]
}
