<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { formatMoney } from '@/utils/currency'
import ExpenseForm from './ExpenseForm.vue'
import { expenseCategoryResource, expenseResource, fetchPayableDebts } from './api'
import type { DebtPaymentType, Expense, ExpenseCategoryOption, PayableDebt } from './types'

const { t } = useI18n()

const expenses = ref<Expense[]>([])
const categories = ref<ExpenseCategoryOption[]>([])
const debtBuckets = ref<Record<DebtPaymentType, PayableDebt[]>>({
  customs: [],
  transit: [],
  road_transit: [],
  border: [],
  loading: [],
  trip_other: [],
  supplier: [],
  transporter: [],
})
const loading = ref(true)
const error = ref('')
const showExpenseModal = ref(false)
const period = ref({ start: '', end: '' })

const monitoredDebtTypes = [
  'customs',
  'transit',
  'road_transit',
  'border',
  'loading',
  'trip_other',
] as const

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
  return categoryNames.value[code] ?? t(`expenseCategory.${code}`)
}

function debtLabel(type: (typeof monitoredDebtTypes)[number]): string {
  const keyByType = {
    customs: 'customs',
    transit: 'transit',
    road_transit: 'roadTransit',
    border: 'border',
    loading: 'loading',
    trip_other: 'tripOther',
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

function onExpenseCreated() {
  showExpenseModal.value = false
  load()
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

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <section v-else class="border-ligne overflow-x-auto rounded-xl border bg-white p-4">
      <table class="w-full text-start text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-2 py-1.5 font-medium">{{ t('finance.expensesView.table.date') }}</th>
            <th class="px-2 py-1.5 font-medium">
              {{ t('finance.expensesView.table.category') }}
            </th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.expensesView.table.notes') }}</th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.expensesView.table.status') }}</th>
            <th class="px-2 py-1.5 text-end font-medium">
              {{ t('finance.expensesView.table.amount') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="expense in filteredExpenses"
            :key="expense.id"
            class="border-ligne border-b last:border-0"
          >
            <td class="px-2 py-1.5 whitespace-nowrap">
              <MonoValue :value="expense.date" align="left" />
            </td>
            <td class="px-2 py-1.5">{{ categoryLabel(expense.category) }}</td>
            <td class="px-2 py-1.5">{{ expense.notes || '-' }}</td>
            <td class="px-2 py-1.5 whitespace-nowrap">
              {{ t(`expenseStatus.${expense.status}`) }}
            </td>
            <td class="px-2 py-1.5 text-end whitespace-nowrap">
              <MonoValue :value="formatMoney(expense.amount)" />
            </td>
          </tr>
          <tr v-if="filteredExpenses.length === 0">
            <td colspan="5" class="text-texte-3 px-2 py-4 text-center">
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
          <MonoValue class="mt-2 text-lg font-semibold" align="left" :value="formatMoney(debtRemaining(type))" />
          <p class="text-texte-3 mt-1 text-xs">
            {{ t('finance.expensesView.monitoringRows', debtBuckets[type].length) }}
          </p>
        </div>
      </div>
    </section>

    <Modal
      v-if="showExpenseModal"
      :title="t('finance.expense.title')"
      max-width="max-w-4xl"
      @close="showExpenseModal = false"
    >
      <ExpenseForm
        show-treasury-payment
        @success="onExpenseCreated"
        @cancel="showExpenseModal = false"
      />
    </Modal>
  </div>
</template>
