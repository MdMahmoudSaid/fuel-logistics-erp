import { apiClient } from '@/api/client'
import type { LossToleranceConfig } from './types'

// Singleton resource (backend/apps/core/views.py LossToleranceConfigView) -
// no list/id, just GET/PATCH the one row (or the spec's 100 L default if no
// admin has configured it yet).
export function fetchLossTolerance(): Promise<LossToleranceConfig> {
  return apiClient.get<LossToleranceConfig>('/settings/loss-tolerance/').then((r) => r.data)
}

export function updateLossTolerance(toleranceLitres: string): Promise<LossToleranceConfig> {
  return apiClient
    .patch<LossToleranceConfig>('/settings/loss-tolerance/', { tolerance_litres: toleranceLitres })
    .then((r) => r.data)
}
