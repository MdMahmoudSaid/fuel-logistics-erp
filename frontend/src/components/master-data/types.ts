export type FieldType =
  | 'text'
  | 'number'
  | 'checkbox'
  | 'textarea'
  | 'select'
  | 'password'
  | 'phone'
  | 'pin'

export interface FieldOption {
  value: string
  label: string
}

export interface FieldSchema {
  key: string
  label: string
  type: FieldType
  required?: boolean
  readOnly?: boolean
  options?: FieldOption[]
}
