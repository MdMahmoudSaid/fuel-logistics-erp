import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import ReportsView from '../ReportsView.vue'
import DateRangeFilter from '@/components/DateRangeFilter.vue'
import type { ReportDocument, ReportResponse } from '../types'
import type { FetchReportOptions } from '../api'

// Labels come from the backend document (spec D2) - the view no longer
// translates report content itself.
const DOCUMENT: ReportDocument = {
  title: 'Rapport des trajets',
  company: { name: 'AZUR ÉNERGIE' },
  generated_on: '2026-09-23',
  lang: 'fr',
  direction: 'ltr',
  currency: 'XOF',
  orientation: 'landscape',
  period: { mode: 'open', from: null, to: null, text: 'Toutes périodes' },
  entity: null,
  info: [{ key: 'generated_on', label: 'Généré le', value: '23/09/2026' }],
  tables: [
    {
      key: 't1',
      title: null,
      emphasis: null,
      columns: [
        { field: 'trip_reference', label: 'Trajet', kind: 'ref', align: 'start' },
        {
          field: 'status',
          label: 'Statut',
          kind: 'status',
          align: 'start',
          namespace: 'tripStatus',
          enum_labels: { DELIVERED: 'Livré' },
        },
      ],
    },
  ],
  opening_balance: null,
  summary: [
    { key: 'trips_count', label: 'Nombre de trajets', value: 1, kind: 'count', emphasis: false },
  ],
  empty_text: 'Aucune donnée pour la période sélectionnée.',
  labels: { page: 'Page {n} / {total}' },
}

const fetchReport = vi.fn(
  async (
    reportType: string,
    params: Record<string, string | undefined>,
    options?: FetchReportOptions,
  ): Promise<ReportResponse> => {
    void reportType
    void params
    void options
    return {
      report_type: 'trip-report',
      fields: ['trip_reference', 'status'],
      rows: [{ trip_reference: 'TRIP-1', status: 'DELIVERED' }],
      document: DOCUMENT,
    }
  },
)
const downloadReportExport = vi.fn(
  async (
    reportType: string,
    format: 'csv' | 'xlsx' | 'pdf',
    params: Record<string, string | undefined>,
    lang?: string,
  ) => {
    void reportType
    void format
    void params
    void lang
  },
)

vi.mock('../api', () => ({
  fetchReport: (
    reportType: string,
    params: Record<string, string | undefined>,
    options?: FetchReportOptions,
  ) => fetchReport(reportType, params, options),
  downloadReportExport: (
    reportType: string,
    format: 'csv' | 'xlsx' | 'pdf',
    params: Record<string, string | undefined>,
    lang?: string,
  ) => downloadReportExport(reportType, format, params, lang),
}))

function setAuthPermissions(permissions: Record<string, string[]>) {
  const auth = useAuthStore()
  auth.user = {
    id: 1,
    phone: '+22212345678',
    email: 'admin@example.com',
    full_name: 'Admin',
    role: 1,
    role_detail: { id: 1, name: 'Admin', permissions },
  }
}

describe('ReportsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('runs the selected report and renders its rows with translated status', async () => {
    setAuthPermissions({ reports: ['view', 'export'] })
    const wrapper = mount(ReportsView)

    await wrapper.find('button').trigger('click') // "Run report"
    await flushPromises()

    // Asks for the printable document, in the active UI language (spec D3).
    expect(fetchReport).toHaveBeenCalledWith('customer-statement', expect.any(Object), {
      document: true,
      lang: 'fr',
    })
    expect(wrapper.find('.report-sheet').exists()).toBe(true)
    expect(wrapper.find('h2').text()).toBe('Rapport des trajets')
    expect(wrapper.text()).toContain('TRIP-1')
    // Raw DB enum values are translated (trips.status.DELIVERED -> "Livré"
    // in the default fr locale), never shown as the bare "DELIVERED" string.
    expect(wrapper.text()).toContain('Livré')
    expect(wrapper.text()).not.toContain('DELIVERED')
  })

  it('always shows Imprimer but hides Exporter PDF without export permission', async () => {
    setAuthPermissions({ reports: ['view'] })
    const wrapper = mount(ReportsView)
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Imprimer')
    expect(wrapper.text()).not.toContain('Exporter PDF')
  })

  it('triggers a PDF export when the role has export permission', async () => {
    setAuthPermissions({ reports: ['view', 'export'] })
    const wrapper = mount(ReportsView)
    await wrapper.find('select').setValue('trip-report')
    await wrapper.find('button').trigger('click')
    await flushPromises()

    const exportButton = wrapper.findAll('button').find((b) => b.text() === 'Exporter PDF')
    expect(exportButton).toBeTruthy()
    await exportButton!.trigger('click')
    await flushPromises()

    // DateRangeFilter emits its default preset ("period") on mount, so that's
    // already folded into the params by the time "Run report" is clicked.
    expect(downloadReportExport).toHaveBeenCalledWith(
      'trip-report',
      'pdf',
      { preset: 'period', range: 'period' },
      'fr',
    )
  })

  it('prints only the sheet: the selection zone and page title are hidden while printing', async () => {
    setAuthPermissions({ reports: ['view', 'export'] })
    let duringPrint: {
      toolbar: boolean
      title: boolean
      sheet: boolean
      landscape: boolean
    } | null = null
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {
      duringPrint = {
        toolbar: !!document.querySelector('.no-print[data-print-hidden]'),
        title: !!document.querySelector('h1[data-print-hidden]'),
        sheet: !!document.querySelector('.report-sheet-scroll[data-print-hidden]'),
        landscape: !!document
          .getElementById('report-page-size')
          ?.textContent?.includes('landscape'),
      }
    })
    const wrapper = mount(ReportsView, { attachTo: document.body })
    await wrapper.find('button').trigger('click')
    await flushPromises()

    const printButton = wrapper.findAll('button').find((b) => b.text() === 'Imprimer')
    await printButton!.trigger('click')

    expect(printSpy).toHaveBeenCalled()
    // The mocked report is landscape (trip-report document).
    expect(duringPrint).toEqual({ toolbar: true, title: true, sheet: false, landscape: true })
    window.dispatchEvent(new Event('afterprint'))
    expect(document.querySelector('[data-print-hidden]')).toBeNull()
    printSpy.mockRestore()
    wrapper.unmount()
  })

  describe('"situation courante" (periodless) reports', () => {
    it('hides the period filter and sends no period for the preview and the PDF export', async () => {
      setAuthPermissions({ reports: ['view', 'export'] })
      const wrapper = mount(ReportsView)
      await wrapper.find('select').setValue('customer-outstanding')
      expect(wrapper.findComponent(DateRangeFilter).exists()).toBe(false)

      await wrapper.find('button').trigger('click')
      await flushPromises()
      const exportButton = wrapper.findAll('button').find((b) => b.text() === 'Exporter PDF')
      await exportButton!.trigger('click')
      await flushPromises()

      expect(fetchReport).toHaveBeenCalledWith('customer-outstanding', {}, expect.any(Object))
      expect(downloadReportExport).toHaveBeenCalledWith('customer-outstanding', 'pdf', {}, 'fr')
    })

    it('shows the period filter again, with a fresh period, on a report that uses it', async () => {
      setAuthPermissions({ reports: ['view'] })
      const wrapper = mount(ReportsView)
      await wrapper.find('select').setValue('fuel-stock')
      expect(wrapper.findComponent(DateRangeFilter).exists()).toBe(false)

      await wrapper.find('select').setValue('trip-report')
      await wrapper.find('button').trigger('click')
      await flushPromises()

      expect(wrapper.findComponent(DateRangeFilter).exists()).toBe(true)
      expect(fetchReport).toHaveBeenLastCalledWith(
        'trip-report',
        { preset: 'period', range: 'period' },
        expect.any(Object),
      )
    })
  })

  describe('capital, expense, debt and receivable reports', () => {
    const NEW = [
      ['capital-report', 'Rapport de capital', true],
      ['general-expense-report', 'Dépenses générales', true],
      ['trip-fee-debt-report', 'Dettes de frais de trajet', false],
      ['general-debt-report', 'Dettes générales', false],
      ['general-receivable-report', 'Créances clients (détail)', false],
    ] as const

    it.each(NEW)(
      '%s is selectable with its translated label; the period filter matches its mode',
      async (slug, label, hasPeriod) => {
        setAuthPermissions({ reports: ['view'] })
        const wrapper = mount(ReportsView)

        expect(wrapper.find(`option[value="${slug}"]`).text()).toBe(label)
        await wrapper.find('select').setValue(slug)

        expect(wrapper.findComponent(DateRangeFilter).exists()).toBe(hasPeriod)
      },
    )

    it('sends the fee type (default "all") with the preview and the PDF export, and resets it on type change', async () => {
      setAuthPermissions({ reports: ['view', 'export'] })
      const wrapper = mount(ReportsView)
      await wrapper.find('select').setValue('trip-fee-debt-report')
      const feeSelect = wrapper.find('[data-test="param-select"]')

      expect(feeSelect.findAll('option').map((o) => o.text())).toEqual([
        'Tous',
        'Douane',
        'Transit',
        'Transit routière',
        'Frontière',
        'Chargement',
      ])
      await feeSelect.setValue('customs')
      await wrapper
        .findAll('button')
        .find((b) => b.text() === 'Lancer le rapport')!
        .trigger('click')
      await flushPromises()
      const exportButton = wrapper.findAll('button').find((b) => b.text() === 'Exporter PDF')
      await exportButton!.trigger('click')
      await flushPromises()

      expect(fetchReport).toHaveBeenLastCalledWith(
        'trip-fee-debt-report',
        { fee_type: 'customs' },
        expect.any(Object),
      )
      expect(downloadReportExport).toHaveBeenCalledWith(
        'trip-fee-debt-report',
        'pdf',
        { fee_type: 'customs' },
        'fr',
      )

      await wrapper.find('select').setValue('general-debt-report')
      expect(wrapper.find('[data-test="param-select"]').exists()).toBe(false)
      await wrapper.find('select').setValue('trip-fee-debt-report')
      expect((wrapper.find('[data-test="param-select"]').element as HTMLSelectElement).value).toBe(
        'all',
      )
    })
  })
})
