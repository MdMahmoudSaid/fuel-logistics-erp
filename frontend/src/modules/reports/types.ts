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
]

export interface ReportResponse {
  report_type: string
  fields: string[]
  rows: Record<string, unknown>[]
}
