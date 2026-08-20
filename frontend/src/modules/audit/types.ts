// Mirrors backend/apps/audit/serializers.py's AuditLogSerializer
// (docs/PHASE_6_PLAN.md Etape 5/8).
export interface AuditLog {
  id: number
  user: number | null
  user_email: string | null
  timestamp: string
  action: 'CREATE' | 'UPDATE' | 'DELETE' | 'CANCEL' | 'REVERSE'
  content_type: number
  content_type_label: string
  object_id: number
  previous_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
  reason: string | null
}
