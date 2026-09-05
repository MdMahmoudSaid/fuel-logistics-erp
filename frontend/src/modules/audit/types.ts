// Mirrors backend/apps/audit/serializers.py's AuditLogSerializer
// (docs/PHASE_6_PLAN.md Etape 5/8).
export interface AuditLog {
  id: number
  user: number | null
  user_email: string | null
  // UI recette fix (2026-09-05): full_name, else phone, else email - see
  // AuditLogSerializer.get_user_display_name(). Preferred over user_email
  // for display; user_email is kept for any consumer that needs the raw
  // email specifically.
  user_display_name: string | null
  timestamp: string
  action: 'CREATE' | 'UPDATE' | 'DELETE' | 'CANCEL' | 'REVERSE'
  content_type: number
  content_type_label: string
  object_id: number
  previous_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
  reason: string | null
  summary: AuditLogSummary
}

export interface AuditLogSummary {
  module_key: string
  reference: string | null
  related_party: string | null
  account_label: string | null
  amount: string | null
}
