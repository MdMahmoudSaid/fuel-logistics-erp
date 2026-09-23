// Mirrors backend/apps/reports/views/reports.py's REPORT_REGISTRY (16 V1
// report types, ERP_Specification.md Section 37; docs/PHASE_6_PLAN.md
// Etape 4/8). idParam/idLabel are set only for report types that require
// an entity id filter to return anything meaningful.
export interface ReportTypeOption {
  value: string
  label: string
  idParam?: string
  idLabel?: string
}

export const REPORT_TYPES: ReportTypeOption[] = [
  {
    value: 'customer-statement',
    label: 'Customer statement',
    idParam: 'customer_id',
    idLabel: 'Customer ID',
  },
  {
    value: 'supplier-statement',
    label: 'Supplier statement',
    idParam: 'supplier_id',
    idLabel: 'Supplier ID',
  },
  {
    value: 'transporter-statement',
    label: 'Transporter statement',
    idParam: 'transporter_id',
    idLabel: 'Transporter ID',
  },
  { value: 'truck-history', label: 'Truck history', idParam: 'truck_id', idLabel: 'Truck ID' },
  { value: 'trip-report', label: 'Trip report' },
  { value: 'purchase-report', label: 'Purchase report' },
  { value: 'sales-report', label: 'Sales report' },
  { value: 'expense-report', label: 'Expense report' },
  { value: 'customer-outstanding', label: 'Customer outstanding' },
  { value: 'supplier-outstanding', label: 'Supplier outstanding' },
  { value: 'transporter-outstanding', label: 'Transporter outstanding' },
  { value: 'fuel-stock', label: 'Fuel stock' },
  { value: 'loss-report', label: 'Loss report' },
  { value: 'margin-report', label: 'Margin report' },
  {
    value: 'bank-statement',
    label: 'Bank statement',
    idParam: 'bank_account_id',
    idLabel: 'Bank account ID',
  },
  {
    value: 'cash-statement',
    label: 'Cash statement',
    idParam: 'cash_account_id',
    idLabel: 'Cash account ID',
  },
  {
    value: 'shareholder-statement',
    label: 'Shareholder statement',
    idParam: 'shareholder_id',
    idLabel: 'Shareholder ID',
  },
]

// Mirrors backend/apps/reports/services/report_document.build_report_document
// (docs/superpowers/specs/2026-09-23-rapports-document-comptable-design.md).
// Decimal values arrive as strings; labels are already translated (spec D2).
export type ReportColumnKind =
  'date' | 'text' | 'ref' | 'money' | 'unit_money' | 'quantity' | 'enum' | 'status'

export interface ReportColumn {
  field: string
  label: string
  kind: ReportColumnKind
  align: 'start' | 'end'
  /** enum/status columns: which value family (badge colours depend on it). */
  namespace?: string
  enum_labels?: Record<string, string>
}

export interface ReportTable {
  key: string
  title: string | null
  columns: ReportColumn[]
  /** Rows whose `field` equals `equals` are printed bold (fuel-stock TOTAL). */
  emphasis: { field: string; equals: string } | null
}

export interface ReportSummaryLine {
  key: string
  label: string
  value: string | number | null
  kind: 'money' | 'quantity' | 'count'
  emphasis: boolean
}

export interface ReportDocument {
  title: string
  company: { name: string }
  generated_on: string
  lang: 'fr' | 'en' | 'ar'
  direction: 'ltr' | 'rtl'
  currency: string
  orientation: 'portrait' | 'landscape'
  period: { mode: 'range' | 'open' | 'as_of'; from: string | null; to: string | null; text: string }
  entity: { label: string; name: string } | null
  info: { key: string; label: string; value: string }[]
  tables: ReportTable[]
  opening_balance: { label: string; value: string | number; column: string } | null
  summary: ReportSummaryLine[]
  empty_text: string
  labels: { page: string }
}

export interface ReportResponse {
  report_type: string
  fields: string[]
  rows: Record<string, unknown>[]
  /** Only present when requested with ?document=1 (spec D3). */
  document?: ReportDocument
}
