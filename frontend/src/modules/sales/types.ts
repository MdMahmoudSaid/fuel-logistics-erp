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
