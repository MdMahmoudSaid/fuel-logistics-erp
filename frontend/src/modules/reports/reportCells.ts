// Cell formatting for ReportSheet. Everything is driven by the backend
// document's column `kind` (spec D2) - no client-side report translation.
import { formatMoney, formatUnitMoney, formatQuantity, formatPercent } from '@/utils/currency'
import { formatDateDMY } from '@/utils/date'
import type { ReportColumn, ReportSummaryLine, ReportTable } from './types'

export const EMPTY_CELL = '—'

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === ''
}

export function cellText(column: ReportColumn, value: unknown): string {
  if (isEmpty(value)) return EMPTY_CELL
  const raw = String(value)
  switch (column.kind) {
    case 'date':
      return formatDateDMY(raw)
    case 'money':
      return formatMoney(raw)
    case 'unit_money':
      return formatUnitMoney(raw)
    case 'quantity':
      return formatQuantity(raw)
    case 'percent':
      return formatPercent(raw)
    case 'enum':
    case 'status':
      return column.enum_labels?.[raw] ?? raw
    default:
      return raw
  }
}

export function summaryText(line: ReportSummaryLine): string {
  if (isEmpty(line.value)) return EMPTY_CELL
  const raw = String(line.value)
  if (line.kind === 'money') return formatMoney(raw)
  if (line.kind === 'quantity') return formatQuantity(raw)
  return raw
}

/** Rows of one table: all rows, or only those of its `section` (spec: several row sets in one report). */
export function tableRows(
  table: ReportTable,
  rows: Record<string, unknown>[],
): Record<string, unknown>[] {
  return table.section ? rows.filter((row) => row.section === table.section) : rows
}

export function isEmphasisRow(table: ReportTable, row: Record<string, unknown>): boolean {
  return !!table.emphasis && row[table.emphasis.field] === table.emphasis.equals
}

export type BadgeVariant = 'livre' | 'transit' | 'ecart' | 'critique' | 'neutre'

// Same colour semantics as the previous Reports screen; keyed by the value
// family (`namespace`, from the backend column) because "CANCELLED" is a
// red badge on a purchase order but a neutral one on an expense.
export function badgeVariant(namespace: string | undefined, value: string): BadgeVariant {
  if (namespace === 'purchaseOrderStatus') {
    if (value === 'CONFIRMED') return 'livre'
    if (value === 'CANCELLED') return 'critique'
    return 'neutre'
  }
  if (namespace === 'expenseStatus') {
    if (value === 'PAID') return 'livre'
    if (value === 'PARTIALLY_PAID') return 'ecart'
    if (value === 'CANCELLED') return 'neutre'
    return 'critique' // UNPAID
  }
  if (namespace === 'tripStatus') {
    if (value === 'DELIVERED' || value === 'COMPLETED') return 'livre'
    if (value === 'CANCELLED' || value === 'BLOCKED') return 'critique'
    if (value === 'QUANTITY_CONTROL') return 'ecart'
    return 'transit'
  }
  return 'neutre'
}

// Sign/role colouring for money cells: 'auto' follows the value's own sign;
// fixed 'emerald'/'rose' cover fields whose meaning does not depend on sign
// (a supplier statement's positive balance is always money owed).
const MONEY_TONE: Record<string, 'emerald' | 'rose' | 'auto'> = {
  'customer-statement.debit': 'rose',
  'customer-statement.credit': 'emerald',
  'customer-statement.balance': 'auto',
  'supplier-statement.debit': 'rose',
  'supplier-statement.credit': 'emerald',
  'supplier-statement.balance': 'rose',
  'shareholder-statement.debit': 'rose',
  'shareholder-statement.credit': 'emerald',
  'shareholder-statement.balance': 'auto',
  'customer-outstanding.outstanding': 'emerald',
  'supplier-outstanding.outstanding': 'rose',
  'transporter-outstanding.outstanding': 'rose',
  'transporter-statement.debit': 'rose',
  'transporter-statement.credit': 'emerald',
  'transporter-statement.balance': 'rose',
}

export function moneyToneClass(
  reportType: string,
  column: ReportColumn,
  row: Record<string, unknown>,
): string {
  const raw = row[column.field]
  if (isEmpty(raw)) return ''
  // bank/cash statements store "amount" positive: in/out lives on "type".
  if (column.field === 'amount' && typeof row.type === 'string') {
    if (row.type === 'MONEY_IN') return 'text-emerald-600'
    if (row.type === 'MONEY_OUT') return 'text-rose-600'
  }
  const rule = MONEY_TONE[`${reportType}.${column.field}`]
  const numeric = Number(raw)
  if (rule === 'emerald') return 'text-emerald-600'
  if (rule === 'rose') return 'text-rose-600'
  if (rule === 'auto') return numeric >= 0 ? 'text-emerald-600' : 'text-rose-600'
  return numeric < 0 ? 'text-rose-600' : ''
}
