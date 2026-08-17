export type FieldType = 'text' | 'number' | 'checkbox' | 'textarea' | 'select' | 'password'

export interface FieldOption {
  value: string
  label: string
}

export interface FieldSchema {
  key: string
  label: string
  type: FieldType
  required?: boolean
  options?: FieldOption[]
}
