export type FieldType =
  | 'text'
  | 'number'
  | 'checkbox'
  | 'textarea'
  | 'select'
  | 'password'
  | 'phone'
  | 'pin'
  | 'money'
  | 'quantity'

export interface FieldOption {
  value: string
  label: string
}

// UI recette fix (2026-09-05): lets a `select` field offer a "+ Creer..."
// inline mini-form (e.g. Chauffeur par defaut on the truck form), the same
// idea ExpenseForm.vue already has for expense categories - generalized
// here so any master-data select field can opt in without a bespoke page.
export interface QuickCreateField {
  key: string
  label: string
  type: 'text' | 'phone'
  required?: boolean
}

export interface QuickCreateConfig {
  buttonLabel: string
  errorMessage: string
  fields: QuickCreateField[]
  create: (payload: Record<string, unknown>) => Promise<{ id: number | string; label: string }>
}

export interface FieldSchema {
  key: string
  label: string
  type: FieldType
  required?: boolean
  readOnly?: boolean
  options?: FieldOption[]
  quickCreate?: QuickCreateConfig
}
