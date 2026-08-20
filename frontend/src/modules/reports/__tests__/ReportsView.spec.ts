import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import ReportsView from '../ReportsView.vue'
import type { ReportResponse } from '../types'

const fetchReport = vi.fn(
  async (
    reportType: string,
    params: Record<string, string | undefined>,
  ): Promise<ReportResponse> => {
    void reportType
    void params
    return {
      report_type: 'trip-report',
      fields: ['trip_reference', 'status'],
      rows: [{ trip_reference: 'TRIP-1', status: 'DELIVERED' }],
    }
  },
)
const downloadReportExport = vi.fn(
  async (
    reportType: string,
    format: 'csv' | 'xlsx',
    params: Record<string, string | undefined>,
  ) => {
    void reportType
    void format
    void params
  },
)

vi.mock('../api', () => ({
  fetchReport: (reportType: string, params: Record<string, string | undefined>) =>
    fetchReport(reportType, params),
  downloadReportExport: (
    reportType: string,
    format: 'csv' | 'xlsx',
    params: Record<string, string | undefined>,
  ) => downloadReportExport(reportType, format, params),
}))

function setAuthPermissions(permissions: Record<string, string[]>) {
  const auth = useAuthStore()
  auth.user = {
    id: 1,
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

  it('runs the selected report and renders its rows', async () => {
    setAuthPermissions({ reports: ['view', 'export'] })
    const wrapper = mount(ReportsView)

    await wrapper.find('button').trigger('click') // "Run report"
    await flushPromises()

    expect(fetchReport).toHaveBeenCalled()
    expect(wrapper.text()).toContain('TRIP-1')
    expect(wrapper.text()).toContain('DELIVERED')
  })

  it('shows export buttons only when the role has export permission', async () => {
    setAuthPermissions({ reports: ['view'] })
    const wrapper = mount(ReportsView)
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('Export CSV')
  })

  it('triggers a CSV export when the role has export permission', async () => {
    setAuthPermissions({ reports: ['view', 'export'] })
    const wrapper = mount(ReportsView)
    await wrapper.find('select').setValue('trip-report')
    await wrapper.find('button').trigger('click')
    await flushPromises()

    const exportButton = wrapper.findAll('button').find((b) => b.text() === 'Export CSV')
    expect(exportButton).toBeTruthy()
    await exportButton!.trigger('click')
    await flushPromises()

    // DateRangeFilter emits its default preset ("month") on mount, so that's
    // already folded into the params by the time "Run report" is clicked.
    expect(downloadReportExport).toHaveBeenCalledWith('trip-report', 'csv', { range: 'month' })
  })
})
