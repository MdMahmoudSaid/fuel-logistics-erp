// What differs between the four document lists (DocumentList.vue).
import { QUOTATION_STATUSES } from '@/modules/quotations/types'
import type { DocumentKind, DocumentRow } from './types'

export interface DocumentConfig {
  kind: DocumentKind
  path: string
  module: 'sales' | 'purchasing'
  i18n: string // documents.<i18n>.*
  listRoute: string
  newRoute: string
  detailRoute: string
  filename: string
  dateField: string
  partner: (row: DocumentRow) => string
  value: { field: string; kind: 'money' | 'litres' }
  statuses?: { values: readonly string[]; labelPrefix: string }
  duplicatePath?: string
}

const name = (detail: unknown) => (detail as { name?: string } | null)?.name ?? ''

export const DOCUMENT_CONFIGS: Record<DocumentKind, DocumentConfig> = {
  proforma: {
    kind: 'proforma',
    listRoute: 'proformas',
    path: '/quotations/',
    module: 'sales',
    i18n: 'proforma',
    newRoute: 'quotation-new',
    detailRoute: 'quotation-detail',
    filename: 'proforma',
    dateField: 'issue_date',
    partner: (row) => name(row.customer_detail) || String(row.customer_name ?? ''),
    value: { field: 'total_amount', kind: 'money' },
    statuses: { values: QUOTATION_STATUSES, labelPrefix: 'quotationStatus.' },
    duplicatePath: '/quotations/',
  },
  delivery: {
    kind: 'delivery',
    listRoute: 'delivery-notes',
    path: '/delivery-notes/',
    module: 'sales',
    i18n: 'delivery',
    newRoute: 'delivery-note-new',
    detailRoute: 'delivery-note-detail',
    filename: 'bon-livraison',
    dateField: 'date',
    partner: (row) => name(row.customer_detail),
    value: { field: 'total_quantity', kind: 'litres' },
  },
  loading: {
    kind: 'loading',
    listRoute: 'loading-sheets',
    path: '/loading-sheets/',
    module: 'purchasing',
    i18n: 'loading',
    newRoute: 'loading-sheet-new',
    detailRoute: 'loading-sheet-detail',
    filename: 'bon-chargement',
    dateField: 'date',
    partner: (row) => String(row.supplier_display_name ?? ''),
    value: { field: 'total_litres', kind: 'litres' },
  },
  purchase: {
    kind: 'purchase',
    listRoute: 'purchase-orders',
    path: '/purchase-order-documents/',
    module: 'purchasing',
    i18n: 'purchase',
    newRoute: 'purchase-order-doc-new',
    detailRoute: 'purchase-order-doc-detail',
    filename: 'bon-commande',
    dateField: 'date',
    partner: (row) => String(row.supplier_name ?? ''),
    value: { field: 'total_amount', kind: 'money' },
    statuses: { values: ['DRAFT', 'SENT'], labelPrefix: 'documents.purchase.statuses.' },
  },
}
