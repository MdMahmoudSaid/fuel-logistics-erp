<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { confirmDialog } from '@/composables/useConfirmDialog'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { translateApiError } from '@/i18n/apiErrors'
import { formatMoney } from '@/utils/currency'
import ExpenseForm from './ExpenseForm.vue'
import { useExpenseCategoryLabel } from './expenseCategoryLabel'
import { cancelExpense, expenseCategoryResource, expenseResource, fetchPayableDebts } from './api'
import type { DebtPaymentType, Expense, ExpenseCategoryOption, PayableDebt } from './types'

const { t } = useI18n()
const localisedCategoryLabel = useExpenseCategoryLabel()

const expenses = ref<Expense[]>([])
const categories = ref<ExpenseCategoryOption[]>([])
const debtBuckets = ref<Record<DebtPaymentType, PayableDebt[]>>({
  customs: [],
  transit: [],
  road_transit: [],
  border: [],
  loading: [],
  supplier: [],
  transporter: [],
})
const loading = ref(true)
const error = ref('')
const showExpenseModal = ref(false)
const period = ref({ start: '', end: '' })

// Bug fix (2026-09-06 client feedback): "Depenses generales" had no way to
// correct or remove a mistaken entry, short of leaving it in place forever -
// same edit/delete story TripDetail.vue's own "Frais du trajet" list already
// solved. An UNPAID expense is a plain draft: edit overwrites it in place
// (PATCH, ExpenseForm's editingExpense mode), delete is a real hard DELETE.
// A PAID/PARTIALLY_PAID expense can only be reversed via /cancel/ (backend
// locks amount/category/method once money has actually moved) - cancelling
// still fully removes it from every debt-monitoring total below, because
// ControlledDebtPaymentService only ever sums UNPAID/PARTIALLY_PAID expenses.
const editingExpense = ref<Expense | null>(null)
const actionError = ref('')
const cancellingId = ref<number | null>(null)
const deletingId = ref<number | null>(null)

const monitoredDebtTypes = ['customs', 'transit', 'road_transit', 'border', 'loading'] as const

const categoryNames = computed(() =>
  Object.fromEntries(categories.value.map((category) => [category.code, category.name])),
)

const filteredExpenses = computed(() =>
  expenses.value.filter((expense) => {
    if (period.value.start && expense.date < period.value.start) return false
    if (period.value.end && expense.date > period.value.end) return false
    return true
  }),
)

function categoryLabel(code: string): string {
  // Prefer the localised label; fall back to the backend name only for
  // user-created categories that have no i18n key (seeded system categories
  // ship an English name that must not leak into a French/Arabic UI).
  return localisedCategoryLabel({ code, name: categoryNames.value[code] })
}

function debtLabel(type: (typeof monitoredDebtTypes)[number]): string {
  const keyByType = {
    customs: 'customs',
    transit: 'transit',
    road_transit: 'roadTransit',
    border: 'border',
    loading: 'loading',
  } as const
  return t(`finance.expensesView.monitoring.${keyByType[type]}`)
}

function debtRemaining(type: DebtPaymentType): number {
  return debtBuckets.value[type].reduce((sum, debt) => sum + Number(debt.remaining_amount), 0)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [expenseData, categoryData, ...debts] = await Promise.all([
      expenseResource.list({ unallocated: 'true' }),
      expenseCategoryResource.list({ is_active: true }),
      ...monitoredDebtTypes.map((type) => fetchPayableDebts(type)),
    ])
    expenses.value = expenseData.results
    categories.value = categoryData.results
    monitoredDebtTypes.forEach((type, index) => {
      debtBuckets.value[type] = debts[index] ?? []
    })
  } catch {
    error.value = t('finance.expensesView.loadError')
  } finally {
    loading.value = false
  }
}

function onExpenseSaved() {
  showExpenseModal.value = false
  editingExpense.value = null
  load()
}

function onExpenseModalClosed() {
  showExpenseModal.value = false
  editingExpense.value = null
}

function onEditExpense(expense: Expense) {
  editingExpense.value = expense
  showExpenseModal.value = true
}

async function onCancelExpenseRow(expense: Expense) {
  cancellingId.value = expense.id
  actionError.value = ''
  try {
    await cancelExpense(expense.id)
    await load()
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    actionError.value = translateApiError(detail) || t('finance.expensesView.actionError')
  } finally {
    cancellingId.value = null
  }
}

async function onDeleteExpense(expense: Expense) {
  if (!(await confirmDialog(t('finance.expensesView.deleteExpenseConfirm')))) return
  deletingId.value = expense.id
  actionError.value = ''
  try {
    await expenseResource.remove(expense.id)
    await load()
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    actionError.value = translateApiError(detail) || t('finance.expensesView.actionError')
  } finally {
    deletingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="max-w-7xl space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('finance.expensesView.title') }}
      </h1>
      <Button data-test="new-general-expense" variant="primary" @click="showExpenseModal = true">
        {{ t('finance.expensesView.newExpense') }}
      </Button>
    </div>

    <div class="border-ligne flex flex-wrap items-end gap-3 rounded-xl border bg-white p-4">
      <div class="space-y-1.5">
        <label class="text-texte-2 text-xs font-semibold uppercase" for="expense_period_start">
          {{ t('finance.expensesView.periodStart') }}
        </label>
        <input
          id="expense_period_start"
          v-model="period.start"
          type="date"
          class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        />
      </div>
      <div class="space-y-1.5">
        <label class="text-texte-2 text-xs font-semibold uppercase" for="expense_period_end">
          {{ t('finance.expensesView.periodEnd') }}
        </label>
        <input
          id="expense_period_end"
          v-model="period.end"
          type="date"
          class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        />
      </div>
    </div>

    <AppAlert v-if="error" :message="error" />
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>
    <AppAlert v-if="actionError" :message="actionError" />

    <section v-else class="border-ligne overflow-x-auto rounded-xl border bg-white p-4">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-2 py-1.5 text-center font-medium">
              {{ t('finance.expensesView.table.date') }}
            </th>
            <th class="px-2 py-1.5 text-center font-medium">
              {{ t('finance.expensesView.table.category') }}
            </th>
            <th class="px-2 py-1.5 text-center font-medium">
              {{ t('finance.expensesView.table.notes') }}
            </th>
            <th class="px-2 py-1.5 text-center font-medium">
              {{ t('finance.expensesView.table.status') }}
            </th>
            <th class="px-2 py-1.5 text-center font-medium">
              {{ t('finance.expensesView.table.paidBy') }}
            </th>
            <th class="px-2 py-1.5 text-end font-medium">
              {{ t('finance.expensesView.table.amount') }}
            </th>
            <th class="px-2 py-1.5 text-center font-medium">
              {{ t('finance.expensesView.table.actions') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="expense in filteredExpenses"
            :key="expense.id"
            class="border-ligne border-b last:border-0"
          >
            <td class="px-2 py-1.5 text-center whitespace-nowrap">
              <MonoValue :value="expense.date" align="center" />
            </td>
            <td class="px-2 py-1.5 text-center">{{ categoryLabel(expense.category) }}</td>
            <td class="px-2 py-1.5 text-center">{{ expense.notes || '-' }}</td>
            <td class="px-2 py-1.5 text-center whitespace-nowrap">
              {{ t(`expenseStatus.${expense.status}`) }}
            </td>
            <td class="px-2 py-1.5 text-center" data-test="expense-paid-by">
              <template v-if="expense.paid_via">
                <span class="text-texte-2 text-xs">{{
                  t(`finance.expensesView.paidVia.${expense.paid_via}`)
                }}</span>
                <span v-if="expense.paid_via_name" class="block font-medium">{{
                  expense.paid_via_name
                }}</span>
              </template>
              <span v-else class="text-texte-3">-</span>
            </td>
            <td class="px-2 py-1.5 text-end whitespace-nowrap">
              <MonoValue :value="formatMoney(expense.amount)" />
            </td>
            <td class="px-2 py-1.5 text-center whitespace-nowrap">
              <div v-if="expense.status === 'UNPAID'" class="flex justify-center gap-2">
                <button
                  type="button"
                  data-test="edit-expense"
                  class="text-bitume text-xs hover:brightness-90"
                  @click="onEditExpense(expense)"
                >
                  {{ t('finance.expensesView.editExpense') }}
                </button>
                <button
                  type="button"
                  data-test="delete-expense"
                  class="text-critique text-xs hover:brightness-90 disabled:opacity-50"
                  :disabled="deletingId === expense.id"
                  @click="onDeleteExpense(expense)"
                >
                  {{ t('finance.expensesView.deleteExpense') }}
                </button>
              </div>
              <button
                v-else-if="expense.status === 'PAID' || expense.status === 'PARTIALLY_PAID'"
                type="button"
                data-test="cancel-expense"
                class="text-critique text-xs hover:brightness-90 disabled:opacity-50"
                :disabled="cancellingId === expense.id"
                @click="onCancelExpenseRow(expense)"
              >
                {{ t('finance.expensesView.cancelExpense') }}
              </button>
              <span v-else class="text-texte-3">-</span>
            </td>
          </tr>
          <tr v-if="filteredExpenses.length === 0">
            <td colspan="7" class="text-texte-3 px-2 py-4 text-center">
              {{ t('finance.expensesView.listEmpty') }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="space-y-3">
      <div class="space-y-1">
        <h2 class="font-display text-base font-semibold uppercase">
          {{ t('finance.expensesView.monitoringTitle') }}
        </h2>
        <p class="text-texte-2 text-sm">{{ t('finance.expensesView.monitoringHelp') }}</p>
      </div>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="type in monitoredDebtTypes"
          :key="type"
          data-test="debt-monitoring-card"
          class="border-ligne rounded-lg border bg-white p-4"
        >
          <p class="text-texte-2 text-xs font-semibold uppercase">{{ debtLabel(type) }}</p>
          <MonoValue
            class="mt-2 text-lg font-semibold"
            align="left"
            :value="formatMoney(debtRemaining(type))"
          />
          <p class="text-texte-3 mt-1 text-xs">
            {{ t('finance.expensesView.monitoringRows', debtBuckets[type].length) }}
          </p>
        </div>
      </div>
    </section>

    <Modal
      v-if="showExpenseModal"
      :title="editingExpense ? t('finance.expensesView.editExpense') : t('finance.expense.title')"
      max-width="max-w-4xl"
      @close="onExpenseModalClosed"
    >
      <ExpenseForm
        show-treasury-payment
        :editing-expense="editingExpense"
        @success="onExpenseSaved"
        @cancel="onExpenseModalClosed"
      />
    </Modal>
  </div>
</template>
