// Mirrors backend/apps/quotations/serializers.py. DRF DecimalField values
// are all serialized as strings (never float) - convert with Number(...)
// only where arithmetic is needed.
import type { CustomerBrief, ProductBrief } from '@/modules/sales/types'

export type QuotationStatus = 'DRAFT' | 'SENT' | 'ACCEPTED' | 'REJECTED' | 'EXPIRED'

export const QUOTATION_STATUSES: QuotationStatus[] = [
  'DRAFT',
  'SENT',
  'ACCEPTED',
  'REJECTED',
  'EXPIRED',
]

export interface QuotationLine {
  id: number
  product: number | null
  product_detail: ProductBrief | null
  description: string
  quantity: string
  unit: string
  unit_price: string
  line_total: string
}

// Write payload for a line - id/line_total/product_detail are never sent
// (id is unused since QuotationSerializer._sync_lines() always fully
// replaces the line set on write; line_total/product_detail are
// server-computed).
export interface QuotationLineInput {
  product: number | null
  description: string
  quantity: string
  unit: string
  unit_price: string
}

export interface Quotation {
  id: number
  reference: string
  customer: number | null
  customer_detail: CustomerBrief | null
  customer_name: string
  status: QuotationStatus
  issue_date: string
  validity_date: string | null
  currency: string
  total_amount: string
  notes: string
  lines: QuotationLine[]
  created_by: number
  created_at: string
  updated_at: string
}
