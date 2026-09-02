// Shared shape for DateRangeFilter.vue's emitted value. The canonical keys
// are preset/start_date/end_date; range/from/to are kept as backend-compatible
// aliases for existing report links and tests.
export interface DateRangeValue {
  preset?: string
  start_date?: string
  end_date?: string
  range?: string
  from?: string
  to?: string
}
