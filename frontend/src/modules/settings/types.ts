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

// Mirrors backend/apps/core/serializers.py CompanyProfileSerializer.
export interface CompanyBankAccount {
  id?: number
  bank: string
  swift: string
  account_number: string
  is_active: boolean
}

export interface CompanyProfile {
  name: string
  tagline: string
  tax_id: string
  trade_register: string
  address: string
  city: string
  phone: string
  email: string
  website: string
  bank_accounts: CompanyBankAccount[]
}
