import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import ReportsView from '../ReportsView.vue'
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

    // DateRangeFilter emits its default preset ("month") on mount, so that's
    // already folded into the params by the time "Run report" is clicked.
    expect(downloadReportExport).toHaveBeenCalledWith(
      'trip-report',
      'pdf',
      { preset: 'month', range: 'month' },
      'fr',
    )
  })

  it('calls window.print for the Imprimer button', async () => {
    setAuthPermissions({ reports: ['view', 'export'] })
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    const wrapper = mount(ReportsView)
    await wrapper.find('button').trigger('click')
    await flushPromises()

    const printButton = wrapper.findAll('button').find((b) => b.text() === 'Imprimer')
    await printButton!.trigger('click')

    expect(printSpy).toHaveBeenCalled()
    printSpy.mockRestore()
  })
})
