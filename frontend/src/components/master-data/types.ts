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
  // Bug fix (recette manuelle 2026-09-06): DataTable used to render every
  // `checkbox` column with the generic "Actif"/"Inactif" labels, so a
  // column like Transporteur.is_internal ("Transporteur interne à
  // l'entreprise") was indistinguishable from the real is_active status
  // column right next to it. Optional override for what true/false mean
  // on THIS field; falls back to the generic Actif/Inactif labels when
  // absent (e.g. is_active itself).
  trueLabel?: string
  falseLabel?: string
}
