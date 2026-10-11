<script setup lang="ts">
// Client request 2026-10-11: an associate takes an advance either from
// another associate (no treasury movement, repaid to him directly) or from
// the company. A company advance moves no treasury either when granted -
// like a profit distribution it shows in his grand livre and becomes
// withdrawable; money only leaves treasury when he withdraws it (Retraits).
// It is deducted automatically from his next validated profit share (or
// repaid into treasury). backend/apps/finance/services.py
// ShareholderLoanService.
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppAlert from '@/components/ui/AppAlert.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import Modal from '@/components/ui/Modal.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { confirmDialog } from '@/composables/useConfirmDialog'
import { formatMoney } from '@/utils/currency'
import { recordShareholderLoanRepayment, shareholderLoanResource } from './api'
import type {
  Shareholder,
  ShareholderBalancesSummary,
  ShareholderLoan,
  ShareholderLoanRepayment,
  ShareholderLoanSource,
} from './types'

export interface TreasuryAccountOption {
  id: number
  name: string
  current_balance?: string
}

const props = defineProps<{
  shareholders: Shareholder[]
  balances: ShareholderBalancesSummary | null
  bankAccounts: TreasuryAccountOption[]
  cashAccounts: TreasuryAccountOption[]
}>()
const emit = defineEmits<{ changed: [] }>()

const { t } = useI18n()

const today = () => new Date().toISOString().slice(0, 10)

function extractErrorMessage(e: unknown, fallback: string): string {
  const data = (e as { response?: { data?: Record<string, unknown> } })?.response?.data
  if (!data) return fallback
  const detail = data.detail ?? data.non_field_errors ?? Object.values(data)[0]
  const message = Array.isArray(detail) ? detail[0] : detail
  return typeof message === 'string' ? message : fallback
}

// --- List -------------------------------------------------------------------

const loans = ref<ShareholderLoan[]>([])
const showSettled = ref(false)
const expandedId = ref<number | null>(null)

async function loadLoans() {
  const data = await shareholderLoanResource.list()
  loans.value = [...data.results]
}

onMounted(loadLoans)

// A company advance already deducted from a share but not yet withdrawn
// is still money he can take, so it stays "en cours".
const openLoans = computed(() =>
  loans.value.filter((l) => l.status !== 'REPAID' || Number(l.undrawn_amount) > 0),
)
const visibleLoans = computed(() => (showSettled.value ? loans.value : openLoans.value))
const openCompanyTotal = computed(() =>
  openLoans.value
    .filter((l) => l.source === 'COMPANY')
    .reduce((sum, l) => sum + Number(l.remaining_amount), 0),
)
const openAssociateTotal = computed(() =>
  openLoans.value
    .filter((l) => l.source === 'SHAREHOLDER')
    .reduce((sum, l) => sum + Number(l.remaining_amount), 0),
)

function repaidPercent(loan: ShareholderLoan): number {
  const amount = Number(loan.amount)
  return amount > 0 ? Math.min(100, (Number(loan.amount_repaid) / amount) * 100) : 0
}

function statusVariant(status: string) {
  if (status === 'REPAID') return 'livre' as const
  if (status === 'PARTIALLY_REPAID') return 'transit' as const
  return 'ecart' as const
}

function sourceLabel(loan: ShareholderLoan): string {
  if (loan.source === 'COMPANY') return t('finance.shareholder.advance.fromCompany')
  return t('finance.shareholder.advance.fromAssociate', { name: loan.lender_detail?.name ?? '—' })
}

function repaymentLabel(loan: ShareholderLoan, r: ShareholderLoanRepayment): string {
  if (r.method === 'PROFIT_SHARE') {
    return t('finance.shareholder.advance.history.deducted', {
      period: r.distribution_period ?? '',
    })
  }
  if (r.method === 'CANCEL') return t('finance.shareholder.advance.history.cancelled')
  if (r.method === 'TREASURY') {
    return t('finance.shareholder.advance.history.treasury', { account: r.account_name ?? '—' })
  }
  return t('finance.shareholder.advance.history.direct', { name: loan.lender_detail?.name ?? '—' })
}

// --- New advance form -----------------------------------------------------

const source = ref<ShareholderLoanSource>('COMPANY')
const form = ref({
  borrower: '',
  lender: '',
  amount: '',
  date: today(),
  notes: '',
})
const formError = ref('')
const saving = ref(false)

const choices = computed(() => [
  {
    value: 'COMPANY' as const,
    icon: 'landmark' as const,
    title: t('finance.shareholder.advance.sourceCompany'),
    text: t('finance.shareholder.advance.sourceCompanyText'),
  },
  {
    value: 'SHAREHOLDER' as const,
    icon: 'users' as const,
    title: t('finance.shareholder.advance.sourceAssociate'),
    text: t('finance.shareholder.advance.sourceAssociateText'),
  },
])

const lenderOptions = computed(() =>
  props.shareholders.filter((s) => String(s.id) !== form.value.borrower),
)

watch(
  () => form.value.borrower,
  (borrower) => {
    if (borrower && borrower === form.value.lender) form.value.lender = ''
  },
)

const borrowerName = computed(
  () => props.shareholders.find((s) => String(s.id) === form.value.borrower)?.name ?? '',
)
const lenderName = computed(
  () => props.shareholders.find((s) => String(s.id) === form.value.lender)?.name ?? '',
)
const lenderAvailable = computed(() => {
  if (!form.value.lender || !props.balances) return null
  const row = props.balances.shareholders.find((s) => String(s.id) === form.value.lender)
  return row ? Number(row.available_balance) : null
})
const amountValue = computed(() => Number(form.value.amount) || 0)

// Same ceilings as the backend, shown before submitting.
const blockingIssue = computed(() => {
  if (amountValue.value <= 0) return ''
  if (source.value === 'SHAREHOLDER' && lenderAvailable.value != null) {
    if (amountValue.value > lenderAvailable.value) {
      return t('finance.shareholder.advance.lenderTooLow')
    }
  }
  return ''
})

const formReady = computed(
  () =>
    !!form.value.borrower &&
    amountValue.value > 0 &&
    !!form.value.date &&
    (source.value === 'COMPANY' || !!form.value.lender) &&
    !blockingIssue.value,
)

function resetForm() {
  form.value = {
    borrower: '',
    lender: '',
    amount: '',
    date: today(),
    notes: '',
  }
}

async function onCreate() {
  if (!formReady.value) return
  const amount = formatMoney(form.value.amount)
  const message =
    source.value === 'COMPANY'
      ? t('finance.shareholder.advance.confirmCompany', {
          name: borrowerName.value,
          amount,
        })
      : t('finance.shareholder.advance.confirmAssociate', {
          name: borrowerName.value,
          amount,
          lender: lenderName.value,
        })
  if (!(await confirmDialog(message))) return
  saving.value = true
  formError.value = ''
  try {
    const isCompany = source.value === 'COMPANY'
    await shareholderLoanResource.create({
      source: source.value,
      borrower: Number(form.value.borrower),
      lender: isCompany ? null : Number(form.value.lender),
      amount: String(form.value.amount),
      date: form.value.date,
      notes: form.value.notes,
    })
    resetForm()
    await loadLoans()
    emit('changed')
  } catch (e) {
    formError.value = extractErrorMessage(e, t('finance.shareholder.loan.saveError'))
  } finally {
    saving.value = false
  }
}

// --- Repayment --------------------------------------------------------------

const repaying = ref<ShareholderLoan | null>(null)
const repayment = ref({
  amount: '',
  date: today(),
  account_type: 'cash' as 'bank' | 'cash',
  account_id: '',
  notes: '',
})
const repaymentError = ref('')
const savingRepayment = ref(false)

const repaymentAccounts = computed(() =>
  repayment.value.account_type === 'bank' ? props.bankAccounts : props.cashAccounts,
)
const repaymentTooHigh = computed(
  () =>
    !!repaying.value && Number(repayment.value.amount) > Number(repaying.value.remaining_amount),
)
// Company advance (client correction 2026-10-11): the part never withdrawn
// is cancelled with no money moving; only the rest - money that really
// left treasury - comes back into an account. Same split as the backend.
const repaymentSplit = computed(() => {
  const loan = repaying.value
  const amount = Math.max(0, Number(repayment.value.amount) || 0)
  if (!loan || loan.source !== 'COMPANY') return { cancelled: 0, cash: amount }
  const cancelled = Math.min(amount, Number(loan.undrawn_amount))
  return { cancelled, cash: amount - cancelled }
})
const needsAccount = computed(
  () => repaying.value?.source === 'COMPANY' && repaymentSplit.value.cash > 0,
)
const repaymentReady = computed(
  () =>
    !!repaying.value &&
    Number(repayment.value.amount) > 0 &&
    !repaymentTooHigh.value &&
    !!repayment.value.date &&
    (!needsAccount.value || !!repayment.value.account_id),
)

function openRepayment(loan: ShareholderLoan) {
  repaying.value = loan
  repayment.value = {
    amount: loan.remaining_amount,
    date: today(),
    account_type: 'cash',
    account_id: '',
    notes: '',
  }
  repaymentError.value = ''
}

async function onRepay() {
  const loan = repaying.value
  if (!loan || !repaymentReady.value) return
  savingRepayment.value = true
  repaymentError.value = ''
  try {
    const isCompany = needsAccount.value
    await recordShareholderLoanRepayment(loan.id, {
      amount: Number(repayment.value.amount).toFixed(2),
      date: repayment.value.date,
      bank_account:
        isCompany && repayment.value.account_type === 'bank'
          ? Number(repayment.value.account_id)
          : null,
      cash_account:
        isCompany && repayment.value.account_type === 'cash'
          ? Number(repayment.value.account_id)
          : null,
      notes: repayment.value.notes,
    })
    repaying.value = null
    await loadLoans()
    emit('changed')
  } catch (e) {
    repaymentError.value = extractErrorMessage(e, t('finance.shareholder.loan.saveError'))
  } finally {
    savingRepayment.value = false
  }
}

const typeFieldClass =
  'border-ligne-forte h-12 w-28 shrink-0 rounded-lg border bg-white px-3 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'
const fieldClass =
  'border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'
</script>

<template>
  <Card :title="t('finance.shareholder.advance.title')">
    <div data-test="shareholder-advances" class="space-y-6">
      <!-- New advance -->
      <form class="space-y-4" @submit.prevent="onCreate">
        <AppAlert v-if="formError" :message="formError" />
        <fieldset class="space-y-2">
          <legend class="text-texte-2 mb-2 text-sm font-medium">
            {{ t('finance.shareholder.advance.question') }}
          </legend>
          <div class="grid gap-3 sm:grid-cols-2">
            <label
              v-for="choice in choices"
              :key="choice.value"
              :data-test="`advance-source-${choice.value}`"
              class="relative flex cursor-pointer gap-3 rounded-xl border-2 bg-white p-3 transition-colors"
              :class="
                source === choice.value ? 'border-bitume' : 'border-ligne hover:border-ligne-forte'
              "
            >
              <input v-model="source" type="radio" class="sr-only" :value="choice.value" />
              <span
                class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
                :class="source === choice.value ? 'bg-bitume text-white' : 'bg-sable text-texte-2'"
              >
                <Icon :name="choice.icon" :size="18" />
              </span>
              <span class="space-y-0.5">
                <span class="text-texte block text-sm font-semibold">{{ choice.title }}</span>
                <span class="text-texte-2 block text-xs leading-snug">{{ choice.text }}</span>
              </span>
            </label>
          </div>
        </fieldset>

        <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div class="space-y-1.5">
            <label class="text-texte-2 text-sm font-medium" for="advance_borrower">
              {{ t('finance.shareholder.advance.borrower') }}
            </label>
            <select
              id="advance_borrower"
              v-model="form.borrower"
              data-test="advance-borrower"
              required
              :class="fieldClass"
            >
              <option value="" disabled>{{ t('finance.shareholder.selectShareholder') }}</option>
              <option v-for="s in shareholders" :key="s.id" :value="String(s.id)">
                {{ s.name }}
              </option>
            </select>
          </div>

          <div v-if="source === 'SHAREHOLDER'" class="space-y-1.5">
            <label class="text-texte-2 text-sm font-medium" for="advance_lender">
              {{ t('finance.shareholder.advance.lender') }}
            </label>
            <select
              id="advance_lender"
              v-model="form.lender"
              data-test="advance-lender"
              required
              :class="fieldClass"
            >
              <option value="" disabled>{{ t('finance.shareholder.selectShareholder') }}</option>
              <option v-for="s in lenderOptions" :key="s.id" :value="String(s.id)">
                {{ s.name }}
              </option>
            </select>
            <p v-if="lenderAvailable != null" class="text-texte-3 text-xs">
              {{ t('finance.shareholder.advance.lenderAvailable') }} :
              <MonoValue class="inline" :value="formatMoney(lenderAvailable)" />
            </p>
          </div>

          <div class="space-y-1.5">
            <label class="text-texte-2 text-sm font-medium" for="advance_amount">
              {{ t('finance.shareholder.loan.amount') }}
            </label>
            <input
              id="advance_amount"
              v-model="form.amount"
              data-test="advance-amount"
              type="number"
              step="0.01"
              min="0.01"
              required
              :class="fieldClass"
            />
          </div>
          <div class="space-y-1.5">
            <label class="text-texte-2 text-sm font-medium" for="advance_date">
              {{ t('finance.shareholder.loan.date') }}
            </label>
            <input
              id="advance_date"
              v-model="form.date"
              type="date"
              :max="today()"
              required
              :class="fieldClass"
            />
          </div>
          <div class="space-y-1.5 md:col-span-2">
            <label class="text-texte-2 text-sm font-medium" for="advance_notes">
              {{ t('masterData.fields.notes') }}
            </label>
            <input
              id="advance_notes"
              v-model="form.notes"
              :placeholder="t('finance.shareholder.advance.notesPlaceholder')"
              :class="fieldClass"
            />
          </div>
        </div>

        <!-- What recording this will do, in plain words. -->
        <div
          v-if="form.borrower && amountValue > 0"
          data-test="advance-effect"
          class="border-ligne bg-sable/60 rounded-xl border p-4 text-sm"
        >
          <p class="text-texte mb-2 font-semibold">
            {{ t('finance.shareholder.advance.effectTitle') }}
          </p>
          <ul class="text-texte-2 list-disc space-y-1 ps-5">
            <template v-if="source === 'COMPANY'">
              <li>
                {{
                  t('finance.shareholder.advance.effectCompanyDebt', {
                    name: borrowerName,
                    amount: formatMoney(amountValue),
                  })
                }}
              </li>
              <li>{{ t('finance.shareholder.advance.effectNoTreasuryYet') }}</li>
              <li class="text-texte font-medium">
                {{ t('finance.shareholder.advance.effectDeduction') }}
              </li>
            </template>
            <template v-else>
              <li>
                {{
                  t('finance.shareholder.advance.effectAssociateDebt', {
                    name: borrowerName,
                    amount: formatMoney(amountValue),
                    lender: lenderName || '…',
                  })
                }}
              </li>
              <li>
                {{
                  t('finance.shareholder.advance.effectAssociateOwes', {
                    name: borrowerName,
                    amount: formatMoney(amountValue),
                    lender: lenderName || '…',
                  })
                }}
              </li>
              <li>{{ t('finance.shareholder.advance.effectNoTreasury') }}</li>
              <li class="text-texte font-medium">
                {{ t('finance.shareholder.advance.effectRepayAssociate') }}
              </li>
            </template>
          </ul>
          <p
            v-if="blockingIssue"
            data-test="advance-blocking"
            class="text-critique mt-2 text-sm font-medium"
          >
            {{ blockingIssue }}
          </p>
        </div>

        <div class="flex justify-end">
          <Button
            data-test="advance-submit"
            type="submit"
            variant="primary"
            :loading="saving"
            :disabled="!formReady"
          >
            {{ t('finance.shareholder.loan.record') }}
          </Button>
        </div>
      </form>

      <!-- Outstanding totals -->
      <div class="grid gap-3 sm:grid-cols-2">
        <div class="border-ligne rounded-xl border bg-white p-4">
          <p class="text-texte-2 flex items-center gap-2 text-xs">
            <Icon name="landmark" :size="14" />{{ t('finance.shareholder.advance.openCompany') }}
          </p>
          <MonoValue
            class="text-lg font-semibold"
            align="left"
            :value="formatMoney(openCompanyTotal)"
          />
        </div>
        <div class="border-ligne rounded-xl border bg-white p-4">
          <p class="text-texte-2 flex items-center gap-2 text-xs">
            <Icon name="users" :size="14" />{{ t('finance.shareholder.advance.openAssociate') }}
          </p>
          <MonoValue
            class="text-lg font-semibold"
            align="left"
            :value="formatMoney(openAssociateTotal)"
          />
        </div>
      </div>

      <!-- List -->
      <div class="space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="text-texte font-semibold">{{ t('finance.shareholder.advance.listTitle') }}</h3>
          <div class="border-ligne flex rounded-lg border bg-white p-0.5 text-sm">
            <button
              type="button"
              data-test="advance-filter-open"
              class="rounded-md px-3 py-1.5"
              :class="!showSettled ? 'bg-bitume text-sable' : 'text-texte-2'"
              @click="showSettled = false"
            >
              {{ t('finance.shareholder.advance.filterOpen', { n: openLoans.length }) }}
            </button>
            <button
              type="button"
              data-test="advance-filter-all"
              class="rounded-md px-3 py-1.5"
              :class="showSettled ? 'bg-bitume text-sable' : 'text-texte-2'"
              @click="showSettled = true"
            >
              {{ t('finance.shareholder.advance.filterAll', { n: loans.length }) }}
            </button>
          </div>
        </div>

        <article
          v-for="loan in visibleLoans"
          :key="loan.id"
          :data-test="`advance-${loan.id}`"
          class="border-ligne rounded-xl border bg-white p-4"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="flex min-w-0 gap-3">
              <span
                class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
                :class="
                  loan.source === 'COMPANY' ? 'bg-ecart-tint text-ecart' : 'bg-sable text-texte-2'
                "
              >
                <Icon :name="loan.source === 'COMPANY' ? 'landmark' : 'users'" :size="18" />
              </span>
              <div class="min-w-0">
                <p class="text-texte font-semibold">{{ loan.borrower_detail?.name }}</p>
                <p class="text-texte-2 text-xs">{{ sourceLabel(loan) }} · {{ loan.date }}</p>
                <p v-if="loan.notes" class="text-texte-3 mt-0.5 text-xs">{{ loan.notes }}</p>
              </div>
            </div>
            <div class="text-end">
              <Badge :variant="statusVariant(loan.status)">
                {{ t(`finance.shareholder.loan.statusValues.${loan.status}`) }}
              </Badge>
              <MonoValue class="mt-1 text-lg font-semibold" :value="formatMoney(loan.amount)" />
            </div>
          </div>

          <div class="mt-3">
            <div class="bg-sable h-1.5 overflow-hidden rounded-full">
              <div
                class="bg-livre h-full rounded-full"
                :style="{ width: `${repaidPercent(loan)}%` }"
              />
            </div>
            <div class="text-texte-2 mt-1.5 flex flex-wrap justify-between gap-2 text-xs">
              <span>
                {{ t('finance.shareholder.advance.repaid') }} :
                <MonoValue class="inline" :value="formatMoney(loan.amount_repaid)" />
              </span>
              <span class="text-texte font-medium">
                {{ t('finance.shareholder.loan.remaining') }} :
                <MonoValue class="inline" :value="formatMoney(loan.remaining_amount)" />
              </span>
            </div>
          </div>

          <div
            v-if="loan.source === 'COMPANY'"
            :data-test="`advance-drawn-${loan.id}`"
            class="border-ligne mt-3 grid gap-2 border-t pt-3 text-xs sm:grid-cols-2"
          >
            <p class="text-texte-2">
              {{ t('finance.shareholder.advance.drawn') }} :
              <MonoValue class="inline" :value="formatMoney(loan.amount_drawn)" />
            </p>
            <p
              class="sm:text-end"
              :class="Number(loan.undrawn_amount) > 0 ? 'text-texte font-medium' : 'text-texte-3'"
            >
              {{ t('finance.shareholder.advance.undrawn') }} :
              <MonoValue class="inline" :value="formatMoney(loan.undrawn_amount)" />
            </p>
            <p v-if="loan.status !== 'REPAID'" class="text-texte-3 sm:col-span-2">
              {{ t('finance.shareholder.advance.autoDeductionHint') }}
            </p>
          </div>

          <div class="mt-3 flex flex-wrap justify-end gap-2">
            <Button
              v-if="loan.repayments.length"
              variant="ghost"
              :data-test="`advance-history-${loan.id}`"
              @click="expandedId = expandedId === loan.id ? null : loan.id"
            >
              {{ t('finance.shareholder.advance.history.toggle', { n: loan.repayments.length }) }}
            </Button>
            <Button
              v-if="loan.status !== 'REPAID'"
              variant="secondary"
              :data-test="`advance-repay-${loan.id}`"
              @click="openRepayment(loan)"
            >
              {{ t('finance.shareholder.advance.repay') }}
            </Button>
          </div>

          <ol
            v-if="expandedId === loan.id"
            class="border-ligne mt-3 space-y-2 border-t pt-3 text-sm"
          >
            <li
              v-for="r in loan.repayments"
              :key="r.id"
              class="flex flex-wrap items-start justify-between gap-2"
            >
              <div>
                <p class="text-texte">{{ repaymentLabel(loan, r) }}</p>
                <p class="text-texte-3 text-xs">
                  {{ r.date }}<template v-if="r.notes && r.method !== 'PROFIT_SHARE'"> · {{ r.notes }}</template>
                </p>
              </div>
              <MonoValue class="text-livre" :value="`− ${formatMoney(r.amount)}`" />
            </li>
          </ol>
        </article>

        <p
          v-if="visibleLoans.length === 0"
          class="border-ligne text-texte-3 rounded-xl border border-dashed px-3 py-8 text-center text-sm"
        >
          {{ t('finance.shareholder.advance.empty') }}
        </p>
      </div>
    </div>

    <Modal
      v-if="repaying"
      :title="t('finance.shareholder.advance.repayTitle')"
      max-width="max-w-xl"
      @close="repaying = null"
    >
      <form data-test="advance-repay-form" class="space-y-4" @submit.prevent="onRepay">
        <div
          class="bg-sable flex flex-wrap items-center justify-between gap-2 rounded-xl p-3 text-sm"
        >
          <div>
            <p class="text-texte font-semibold">{{ repaying.borrower_detail?.name }}</p>
            <p class="text-texte-2 text-xs">{{ sourceLabel(repaying) }} · {{ repaying.date }}</p>
          </div>
          <div class="text-end">
            <p class="text-texte-2 text-xs">{{ t('finance.shareholder.loan.remaining') }}</p>
            <MonoValue class="font-semibold" :value="formatMoney(repaying.remaining_amount)" />
          </div>
        </div>

        <p class="text-texte-2 text-sm">
          {{
            repaying.source === 'COMPANY'
              ? t('finance.shareholder.advance.repayCompanyHelp')
              : t('finance.shareholder.advance.repayAssociateHelp', {
                  name: repaying.borrower_detail?.name ?? '',
                  lender: repaying.lender_detail?.name ?? '',
                })
          }}
        </p>
        <AppAlert v-if="repaymentError" :message="repaymentError" />

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div class="space-y-1.5">
            <label class="text-texte-2 text-sm font-medium" for="repay_amount">
              {{ t('finance.shareholder.loan.amount') }}
            </label>
            <input
              id="repay_amount"
              v-model="repayment.amount"
              data-test="repay-amount"
              type="number"
              step="0.01"
              min="0.01"
              :max="repaying.remaining_amount"
              required
              :class="fieldClass"
            />
            <p v-if="repaymentTooHigh" class="text-critique text-xs">
              {{ t('finance.shareholder.advance.repayTooHigh') }}
            </p>
          </div>
          <div class="space-y-1.5">
            <label class="text-texte-2 text-sm font-medium" for="repay_date">
              {{ t('finance.shareholder.loan.date') }}
            </label>
            <input
              id="repay_date"
              v-model="repayment.date"
              type="date"
              :max="today()"
              required
              :class="fieldClass"
            />
          </div>
          <div
            v-if="repaying.source === 'COMPANY' && Number(repayment.amount) > 0"
            data-test="repay-split"
            class="border-ligne bg-sable/60 space-y-1 rounded-xl border p-3 text-sm sm:col-span-2"
          >
            <p v-if="repaymentSplit.cancelled > 0" class="text-texte-2">
              {{
                t('finance.shareholder.advance.repaySplitCancel', {
                  amount: formatMoney(repaymentSplit.cancelled),
                })
              }}
            </p>
            <p v-if="repaymentSplit.cash > 0" class="text-texte font-medium">
              {{
                t('finance.shareholder.advance.repaySplitCash', {
                  amount: formatMoney(repaymentSplit.cash),
                })
              }}
            </p>
          </div>
          <div v-if="needsAccount" class="space-y-1.5 sm:col-span-2">
            <span class="text-texte-2 text-sm font-medium">
              {{ t('finance.shareholder.advance.repayAccount') }}
            </span>
            <div class="flex gap-2">
              <select
                v-model="repayment.account_type"
                :aria-label="t('finance.shareholder.withdrawal.accountType')"
                :class="typeFieldClass"
                @change="repayment.account_id = ''"
              >
                <option value="cash">{{ t('finance.transfer.cash') }}</option>
                <option value="bank">{{ t('finance.transfer.bank') }}</option>
              </select>
              <select
                v-model="repayment.account_id"
                data-test="repay-account"
                required
                :aria-label="t('finance.shareholder.advance.repayAccount')"
                class="min-w-0 flex-1"
                :class="fieldClass"
              >
                <option value="" disabled>{{ t('finance.transfer.selectAccount') }}</option>
                <option v-for="a in repaymentAccounts" :key="a.id" :value="String(a.id)">
                  {{ a.name }}
                </option>
              </select>
            </div>
          </div>
          <div class="space-y-1.5 sm:col-span-2">
            <label class="text-texte-2 text-sm font-medium" for="repay_notes">
              {{ t('masterData.fields.notes') }}
            </label>
            <input id="repay_notes" v-model="repayment.notes" :class="fieldClass" />
          </div>
        </div>

        <div class="flex justify-end gap-3">
          <Button variant="ghost" @click="repaying = null">{{ t('common.cancel') }}</Button>
          <Button
            data-test="repay-submit"
            type="submit"
            variant="primary"
            :loading="savingRepayment"
            :disabled="!repaymentReady"
          >
            {{ t('finance.shareholder.advance.repaySubmit') }}
          </Button>
        </div>
      </form>
    </Modal>
  </Card>
</template>
