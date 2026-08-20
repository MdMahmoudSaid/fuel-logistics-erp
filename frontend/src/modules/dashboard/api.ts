import { apiClient } from '@/api/client'
import type { DashboardSummary } from './types'

export function fetchDashboardSummary(
  params: Record<string, string | undefined>,
): Promise<DashboardSummary> {
  return apiClient.get<DashboardSummary>('/dashboard/summary/', { params }).then((r) => r.data)
}
