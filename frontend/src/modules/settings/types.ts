// Mirrors backend/apps/core/serializers.py LossToleranceConfigSerializer.

export interface UserBrief {
  id: number
  email: string
  full_name: string
}

export interface LossToleranceConfig {
  tolerance_litres: string
  updated_by: number | null
  updated_by_detail: UserBrief | null
  updated_at: string | null
}
