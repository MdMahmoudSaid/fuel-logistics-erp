import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ReportSheet from '../ReportSheet.vue'
import type { ReportDocument } from '../types'

// The sheet renders exactly what the backend document says (spec D2): these
// fixtures mimic apps/reports/services/report_document.build_report_document.
const BASE: ReportDocument = {
  title: 'Relevé client',
  company: { name: 'AZUR ÉNERGIE' },
  generated_on: '2026-09-23',
  lang: 'fr',
  direction: 'ltr',
  currency: 'XOF',
  orientation: 'portrait',
  period: {
    mode: 'range',
    from: '2026-09-01',
    to: '2026-09-23',
    text: 'Du 01/09/2026 au 23/09/2026',
  },
  entity: { label: 'Client', name: 'Ets Diallo' },
  info: [
    { key: 'generated_on', label: 'Généré le', value: '23/09/2026' },
    { key: 'period', label: 'Période', value: 'Du 01/09/2026 au 23/09/2026' },
    { key: 'entity', label: 'Client', value: 'Ets Diallo' },
    { key: 'currency', label: 'Devise', value: 'XOF' },
  ],
  tables: [
    {
      key: 't1',
      title: null,
      emphasis: null,
      columns: [
        { field: 'date', label: 'Date', kind: 'date', align: 'start' },
        {
          field: 'type',
          label: 'Type',
          kind: 'enum',
          align: 'start',
          namespace: 'statementType',
          enum_labels: { INVOICE: 'Facture', PAYMENT: 'Paiement' },
        },
        { field: 'reference', label: 'Référence', kind: 'ref', align: 'start' },
        { field: 'debit', label: 'Débit', kind: 'money', align: 'end' },
        { field: 'credit', label: 'Crédit', kind: 'money', align: 'end' },
        { field: 'balance', label: 'Solde', kind: 'money', align: 'end' },
      ],
    },
  ],
  opening_balance: { label: 'Solde antérieur', value: '500000.00', column: 'balance' },
  summary: [
    {
      key: 'opening_balance',
      label: 'Solde antérieur',
      value: '500000.00',
      kind: 'money',
      emphasis: false,
    },
    {
      key: 'total_debit',
      label: 'Total débit',
      value: '1250000.00',
      kind: 'money',
      emphasis: false,
    },
    {
      key: 'cancelled_excluded',
      label: 'Annulés exclus',
      value: 0,
      kind: 'count',
      emphasis: false,
    },
    {
      key: 'closing_balance',
      label: 'Solde final',
      value: '1450000.00',
      kind: 'money',
      emphasis: true,
    },
  ],
  empty_text: 'Aucune donnée pour la période sélectionnée.',
  labels: { page: 'Page {n} / {total}' },
}

const ROWS = [
  {
    date: '2026-09-02',
    type: 'INVOICE',
    reference: 'FAC-1',
    debit: '1250000.00',
    credit: null,
    balance: '1750000.00',
  },
  {
    date: '2026-09-03',
    type: 'PAYMENT',
    reference: 'PAY-1',
    debit: null,
    credit: '300000.00',
    balance: '-1450000.00',
  },
]

// formatMoney/formatQuantity wrap values in LTR isolates and use NBSP.
const clean = (text: string) =>
  text
    .replace(/[\u2066\u2069\u00a0\u202f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

function mountSheet(
  document: ReportDocument = BASE,
  rows: Record<string, unknown>[] = ROWS,
  reportType = 'customer-statement',
) {
  return mount(ReportSheet, { props: { document, rows, reportType } })
}

describe('ReportSheet', () => {
  it('renders the masthead, title and general-information block', () => {
    const wrapper = mountSheet()
    const text = clean(wrapper.text())

    expect(wrapper.find('img').exists()).toBe(true)
    expect(text).toContain('AZUR ÉNERGIE')
    expect(wrapper.find('h2').text()).toBe('Relevé client')
    const info = clean(wrapper.find('.report-info').text())
    for (const expected of [
      'Généré le',
      '23/09/2026',
      'Période',
      'Du 01/09/2026 au 23/09/2026',
      'Client',
      'Ets Diallo',
      'Devise',
      'XOF',
    ]) {
      expect(info).toContain(expected)
    }
  })

  it('never uses a <header> element: the print stylesheet hides every <header> (app topbar)', () => {
    const wrapper = mountSheet()

    expect(wrapper.find('header').exists()).toBe(false)
    expect(wrapper.find('.report-masthead').exists()).toBe(true)
  })

  it('renders translated headers and formatted cells, never raw values', () => {
    const wrapper = mountSheet()
    const headers = wrapper.findAll('thead th').map((th) => th.text())
    const firstRow = wrapper
      .findAll('tbody tr.report-row')[0]!
      .findAll('td')
      .map((td) => clean(td.text()))

    expect(headers).toEqual(['Date', 'Type', 'Référence', 'Débit', 'Crédit', 'Solde'])
    expect(firstRow).toEqual([
      '02/09/2026',
      'Facture',
      'FAC-1',
      '1 250 000 XOF',
      '—',
      '1 750 000 XOF',
    ])
    expect(clean(wrapper.text())).not.toContain('INVOICE')
  })

  it('formats unit prices with 4 decimals, quantities in litres, and status as a badge', () => {
    const document: ReportDocument = {
      ...BASE,
      opening_balance: null,
      tables: [
        {
          key: 't1',
          title: null,
          emphasis: null,
          columns: [
            { field: 'qty', label: 'Qté', kind: 'quantity', align: 'end' },
            { field: 'price', label: 'Prix', kind: 'unit_money', align: 'end' },
            {
              field: 'status',
              label: 'Statut',
              kind: 'status',
              align: 'start',
              namespace: 'purchaseOrderStatus',
              enum_labels: { CANCELLED: 'Annulée' },
            },
          ],
        },
      ],
    }
    const wrapper = mountSheet(
      document,
      [{ qty: '45000.00', price: '600.0000', status: 'CANCELLED' }],
      'purchase-report',
    )
    const cells = wrapper.findAll('tbody tr.report-row td').map((td) => clean(td.text()))

    expect(cells).toEqual(['45 000 L', '600,0000 XOF/L', 'Annulée'])
    expect(wrapper.find('tbody tr.report-row td:nth-child(3) span').classes().join(' ')).toContain(
      'rounded-full',
    )
  })

  it('shows the opening-balance row first, in the balance column, then the rows', () => {
    const wrapper = mountSheet()
    const rows = wrapper.findAll('tbody tr')
    const opening = wrapper.find('tr.report-opening-row')

    expect(rows[0]!.classes()).toContain('report-opening-row')
    expect(clean(opening.text())).toContain('Solde antérieur')
    expect(clean(opening.text())).toContain('500 000 XOF')
    expect(opening.findAll('td').length).toBeLessThanOrEqual(6)
  })

  it('renders the summary lines, emphasizes the final one and prints the cancelled count', () => {
    const wrapper = mountSheet()
    const lines = wrapper.findAll('.report-summary tr').map((tr) =>
      tr
        .findAll('td')
        .map((td) => clean(td.text()))
        .join(' '),
    )

    expect(lines).toEqual([
      'Solde antérieur 500 000 XOF',
      'Total débit 1 250 000 XOF',
      'Annulés exclus 0',
      'Solde final 1 450 000 XOF',
    ])
    expect(wrapper.findAll('.report-summary tr')[3]!.classes().join(' ')).toContain('font-semibold')
    expect(wrapper.findAll('.report-summary tr')[0]!.classes().join(' ')).not.toContain(
      'font-semibold',
    )
  })

  it('keeps headers and summary and shows the empty text when there are no rows', () => {
    const wrapper = mountSheet({ ...BASE, opening_balance: null }, [])

    expect(wrapper.findAll('thead th')).toHaveLength(6)
    expect(wrapper.find('.report-empty').text()).toBe('Aucune donnée pour la période sélectionnée.')
    expect(wrapper.find('.report-empty').attributes('colspan')).toBe('6')
    expect(wrapper.find('.report-summary').exists()).toBe(true)
  })

  it('uses an A4 portrait or landscape sheet width', () => {
    const portrait = mountSheet()
    const landscape = mountSheet({ ...BASE, orientation: 'landscape' })

    expect(portrait.find('.report-sheet').attributes('data-orientation')).toBe('portrait')
    expect(portrait.find('.report-sheet').attributes('style')).toContain('210mm')
    expect(landscape.find('.report-sheet').attributes('data-orientation')).toBe('landscape')
    expect(landscape.find('.report-sheet').attributes('style')).toContain('297mm')
    expect(portrait.find('.report-sheet-scroll').classes()).toContain('overflow-x-auto')
  })

  it('renders an Arabic document right-to-left', () => {
    const wrapper = mountSheet({ ...BASE, lang: 'ar', direction: 'rtl', title: 'كشف حساب العميل' })

    expect(wrapper.find('.report-sheet').attributes('dir')).toBe('rtl')
    expect(wrapper.find('h2').text()).toBe('كشف حساب العميل')
    // Native dir="rtl" flips the table: DOM order stays logical (date first).
    expect(wrapper.findAll('thead th')[0]!.text()).toBe('Date')
  })

  it('renders several titled tables (margin report) and bolds emphasized rows', () => {
    const table = (key: string, title: string) => ({
      key,
      title,
      emphasis: { field: 'component', equals: 'TOTAL' },
      columns: [
        { field: 'component', label: 'Composant', kind: 'text' as const, align: 'start' as const },
        { field: 'quantity', label: 'Quantité', kind: 'quantity' as const, align: 'end' as const },
      ],
    })
    const document: ReportDocument = {
      ...BASE,
      opening_balance: null,
      tables: [
        table('t1', 'Quantités et prix'),
        table('t2', 'Coûts'),
        table('t3', 'Pertes et marge'),
      ],
    }
    const wrapper = mountSheet(
      document,
      [
        { component: 'A', quantity: '10' },
        { component: 'TOTAL', quantity: '10' },
      ],
      'margin-report',
    )

    expect(wrapper.findAll('h3').map((h) => h.text())).toEqual([
      'Quantités et prix',
      'Coûts',
      'Pertes et marge',
    ])
    expect(wrapper.findAll('table.report-table')).toHaveLength(3)
    const totalRow = wrapper.findAll('tbody tr.report-row')[1]!
    expect(totalRow.classes().join(' ')).toContain('font-semibold')
  })

  it('colours signed money like the previous screen: debit rose, credit emerald, negative balance rose', () => {
    const wrapper = mountSheet()
    const [first, second] = wrapper.findAll('tbody tr.report-row')
    const money = (tr: typeof first, index: number) =>
      tr!.findAll('td')[index]!.find('span').classes()

    expect(money(first, 3)).toContain('text-rose-600')
    expect(money(second, 4)).toContain('text-emerald-600')
    expect(money(second, 5)).toContain('text-rose-600')
    expect(money(first, 5)).toContain('text-emerald-600')
  })
})
