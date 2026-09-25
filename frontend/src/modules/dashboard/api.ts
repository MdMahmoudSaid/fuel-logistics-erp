import { apiClient } from '@/api/client'
import type { DashboardSummary } from './types'

export function fetchDashboardSummary(
  params: Record<string, string | undefined>,
): Promise<DashboardSummary> {
  return apiClient.get<DashboardSummary>('/dashboard/summary/', { params }).then((r) => r.data)
}

// GET /api/dashboard/working-capital-pdf/?lines=...&lang= (backend
// apps/reports/views/dashboard.py) - the "Fond de roulement client" card as a
// PDF with only the lines the operator ticked.
export async function downloadWorkingCapitalPdf(lines: string[], lang: string): Promise<void> {
  const response = await apiClient.get('/dashboard/working-capital-pdf/', {
    params: { lines: lines.join(','), lang },
    responseType: 'blob',
  })
  const url = window.URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'fond-de-roulement.pdf'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}
