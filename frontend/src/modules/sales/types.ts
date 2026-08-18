// Mirrors backend/apps/sales/serializers.py. DRF DecimalField / computed
// SerializerMethodField quantities are all serialized as strings (never
// float) — convert with Number(...) only where arithmetic is needed.

export type CustomerOrderStatus =
  | 'DRAFT'
  | 'CONFIRMED'
  | 'PARTIALLY_ASSIGNED'
  | 'IN_PROGRESS'
  | 'PARTIALLY_DELIVERED'
  | 'DELIVERED'
  | 'CLOSED'
  | 'CANCELLED'

// Only these are accepted by CustomerOrderSerializer.validate_status() — the
// rest are derived from trip progress by CustomerOrderService.recompute_status()
// and rejected if set directly (backend/apps/sales/serializers.py).
export const MANUALLY_SETTABLE_STATUSES: CustomerOrderStatus[] = [
  'DRAFT',
  'CONFIRMED',
  'CLOSED',
  'CANCELLED',
]

export interface CustomerBrief {
  id: number
  name: string
  company_name: string
}

export interface ProductBrief {
  id: number
  name: string
  code: string
}

export interface CustomerOrder {
  id: number
  customer: number
  customer_detail: CustomerBrief | null
  product: number
  product_detail: ProductBrief | null
  quantity_ordered: string
  expected_price: string | null
  status: CustomerOrderStatus
  notes: string
  assigned_quantity: string
  loaded_quantity: string
  delivered_quantity: string
  remaining_quantity: string
  created_at: string
  updated_at: string
}

export interface UserBrief {
  id: number
  email: string
  full_name: string
}

// A Sale is generated exclusively by the backend's DeliveryService when a
// trip's delivery is confirmed (backend/apps/sales/serializers.py
// SaleSerializer - entirely read-only) - there is no create/edit form here.
export interface Sale {
  id: number
  trip: number
  trip_reference: string
  customer: number
  customer_detail: CustomerBrief | null
  product: number
  product_detail: ProductBrief | null
  delivered_quantity: string
  unit_selling_price: string
  currency: string
  subtotal: string
  created_at: string
  updated_at: string
}

export type InvoiceStatus = 'DRAFT' | 'VALIDATED' | 'PARTIALLY_PAID' | 'PAID' | 'CANCELLED'

// Fields InvoiceService.correct_invoice() knows how to apply/recompute
// (backend/apps/sales/services.py) - the only ones offered in the
// correction form below.
export const CORRECTABLE_INVOICE_FIELDS = ['unit_selling_price', 'total_amount'] as const
export type CorrectableInvoiceField = (typeof CORRECTABLE_INVOICE_FIELDS)[number]

export interface InvoiceCorrectionEntry {
  id: number
  field_name: string
  previous_value: string
  new_value: string
  corrected_by: number
  corrected_by_detail: UserBrief | null
  corrected_at: string
  reason: string
}

export interface Invoice {
  id: number
  invoice_number: string
  sale: number
  sale_detail: Sale | null
  status: InvoiceStatus
  total_amount: string
  issued_date: string
  corrections: InvoiceCorrectionEntry[]
  created_at: string
  updated_at: string
}
