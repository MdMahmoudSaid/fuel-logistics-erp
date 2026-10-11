// Mirrors backend/apps/commercial_documents/serializers.py.
export type DocumentKind = 'proforma' | 'delivery' | 'loading' | 'purchase'

export interface DocumentRow {
  id: number
  reference: string
  [field: string]: unknown
}

export interface DeliveryNoteLine {
  id?: number
  trip: number | null
  designation: string
  quantity: string
  tanker: string
  tractor: string
  missing: string | null
  observation: string
}

export interface DeliveryNote {
  id: number
  reference: string
  date: string
  customer: number | null
  customer_detail?: { id: number; name: string; address?: string } | null
  place: string
  delivery_address: string
  notes: string
  lines: DeliveryNoteLine[]
  total_quantity?: string
}

export interface DeliverableTrip {
  trip: number
  reference: string
  loading_date: string
  truck: string
  designation: string
  quantity: string
  tanker: string
  tractor: string
  missing: string | null
  other_notes: string[]
}

export interface LoadingSheetLine {
  id?: number
  truck: number | null
  tractor: string
  tanker: string
  capacity_litres: string
  product_name: string
  be_number: string
  route: string
}

export interface LoadingSheet {
  id: number
  reference: string
  date: string
  supplier: number | null
  supplier_name: string
  supplier_display_name?: string
  on_behalf_of: string
  source_reference: string
  product_name: string
  route: string
  notes: string
  lines: LoadingSheetLine[]
  total_litres?: string
}

export interface PurchaseOrderLine {
  id?: number
  product: number | null
  description: string
  quantity: string
  unit: string
  unit_price: string
  line_total?: string
}

export interface PurchaseOrderDocument {
  id: number
  reference: string
  date: string
  supplier: number | null
  supplier_name?: string
  supplier_order: number | null
  delivery_place: string
  delivery_date: string | null
  payment_terms: string
  currency: string
  status: 'DRAFT' | 'SENT'
  total_amount?: string
  notes: string
  lines: PurchaseOrderLine[]
}
