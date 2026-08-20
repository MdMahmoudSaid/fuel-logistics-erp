// Shared shape for DateRangeFilter.vue's emitted value - matches the query
// params backend/apps/reports/date_range.py's resolve_date_range() expects
// (docs/PHASE_6_PLAN.md Etape 7).
export interface DateRangeValue {
  range?: string
  from?: string
  to?: string
}
