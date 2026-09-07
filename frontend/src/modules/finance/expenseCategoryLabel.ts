import { useI18n } from 'vue-i18n'

/**
 * Display label for an expense category.
 *
 * The seeded "system" categories (customs, transit, road_transit, transport,
 * loading, road, …) carry an English `name` straight from the backend seed
 * (apps/finance/migrations/0014_expensecategory.py) — showing that verbatim
 * leaks "Customs"/"Transit"/… into the otherwise-French (or Arabic) UI. Those
 * codes all have a localised `expenseCategory.*` i18n key, so translate
 * through that whenever one exists. A user-created custom category has no
 * such key; its `name` was typed by the user in their own language and is
 * the correct fallback.
 */
export function useExpenseCategoryLabel() {
  const { t, te } = useI18n()
  return (category: { code: string; name?: string | null }): string => {
    const key = `expenseCategory.${category.code}`
    return te(key) ? t(key) : (category.name ?? category.code)
  }
}
