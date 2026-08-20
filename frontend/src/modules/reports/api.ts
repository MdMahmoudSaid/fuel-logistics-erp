import { apiClient } from '@/api/client'
import type { ReportResponse } from './types'

export function fetchReport(
  reportType: string,
  params: Record<string, string | undefined>,
): Promise<ReportResponse> {
  return apiClient.get<ReportResponse>(`/reports/${reportType}/`, { params }).then((r) => r.data)
}

// No existing blob/download helper in this codebase yet (Etape 8 is the
// first report export UI) - builds a temporary <a download> from the
// binary response, same technique every browser file-download flow uses.
export async function downloadReportExport(
  reportType: string,
  format: 'csv' | 'xlsx',
  params: Record<string, string | undefined>,
): Promise<void> {
  const response = await apiClient.get(`/reports/${reportType}/`, {
    params: { ...params, export: format },
    responseType: 'blob',
  })
  const url = window.URL.createObjectURL(new Blob([response.data]))
  const link = document.createElement('a')
  link.href = url
  link.download = `${reportType}.${format}`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}
