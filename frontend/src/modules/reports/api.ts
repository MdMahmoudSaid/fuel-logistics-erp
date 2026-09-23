import { apiClient } from '@/api/client'
import type { ReportResponse } from './types'

export interface FetchReportOptions {
  /** Ask for the printable `document` block (spec D3: opt-in, additive). */
  document?: boolean
  lang?: string
}

export function fetchReport(
  reportType: string,
  params: Record<string, string | undefined>,
  options: FetchReportOptions = {},
): Promise<ReportResponse> {
  const query: Record<string, string | undefined> = { ...params }
  if (options.document) query.document = '1'
  if (options.lang) query.lang = options.lang
  return apiClient
    .get<ReportResponse>(`/reports/${reportType}/`, { params: query })
    .then((r) => r.data)
}

// No existing blob/download helper in this codebase yet (Etape 8 is the
// first report export UI) - builds a temporary <a download> from the
// binary response, same technique every browser file-download flow uses.
export async function downloadReportExport(
  reportType: string,
  format: 'csv' | 'xlsx' | 'pdf',
  params: Record<string, string | undefined>,
  lang?: string,
): Promise<void> {
  const response = await apiClient.get(`/reports/${reportType}/`, {
    params: { ...params, export: format, ...(lang ? { lang } : {}) },
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
