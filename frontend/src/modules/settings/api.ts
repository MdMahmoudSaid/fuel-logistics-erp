import { apiClient } from '@/api/client'
import type { CompanyProfile, LossToleranceConfig } from './types'

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

// Singleton company details printed on the commercial documents
// (backend/apps/core/views.py CompanyProfileView).
export function fetchCompanyProfile(): Promise<CompanyProfile> {
  return apiClient.get<CompanyProfile>('/settings/company/').then((r) => r.data)
}

export function updateCompanyProfile(profile: Partial<CompanyProfile>): Promise<CompanyProfile> {
  return apiClient.patch<CompanyProfile>('/settings/company/', profile).then((r) => r.data)
}
