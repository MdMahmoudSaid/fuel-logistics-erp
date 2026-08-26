// Must match Role.MODULES / Role.ACTIONS in backend/apps/accounts/models.py exactly.
export const MODULES = [
  'operations',
  'finance',
  'sales',
  'purchasing',
  'admin',
  'shareholders',
] as const
export const ACTIONS = ['view', 'create', 'edit', 'validate', 'cancel', 'export'] as const
