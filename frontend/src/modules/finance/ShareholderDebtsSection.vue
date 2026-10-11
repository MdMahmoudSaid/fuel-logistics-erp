<script setup lang="ts">
// Grand livre of one associate: what he owes the company / other associates
// and what they owe him (client request 2026-10-11), each advance with its
// repayment history - ShareholderLedgerService.get_shareholder_summary.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Badge from '@/components/ui/Badge.vue'
import Icon from '@/components/ui/Icon.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { formatMoney } from '@/utils/currency'
import type { ShareholderLedger, ShareholderLedgerLoan, ShareholderLoanRepayment } from './types'

const props = defineProps<{ ledger: ShareholderLedger }>()
const { t } = useI18n()

interface Line {
  key: string
  kind: 'company' | 'owed' | 'receivable'
  loan: ShareholderLedgerLoan
  counterpart: string
}

const lines = computed<Line[]>(() => [
  ...props.ledger.loans_borrowed.map((loan) => ({
    key: `b-${loan.id}`,
    kind: loan.source === 'COMPANY' ? ('company' as const) : ('owed' as const),
    loan,
    counterpart:
      loan.source === 'COMPANY'
        ? t('finance.shareholder.debts.company')
        : (loan.lender_name ?? '—'),
  })),
  ...props.ledger.loans_lent.map((loan) => ({
    key: `l-${loan.id}`,
    kind: 'receivable' as const,
    loan,
    counterpart: loan.borrower_name ?? '—',
  })),
])

const cards = computed(() => [
  {
    key: 'company',
    icon: 'landmark' as const,
    label: t('finance.shareholder.debts.companyDebt'),
    help: t('finance.shareholder.debts.companyDebtHelp'),
    value: props.ledger.company_advance_debt,
    tone: 'text-critique',
    extra:
      Number(props.ledger.company_advance_undrawn) > 0
        ? t('finance.shareholder.debts.undrawn', {
            amount: formatMoney(props.ledger.company_advance_undrawn),
          })
        : '',
  },
  {
    key: 'owed',
    icon: 'users' as const,
    label: t('finance.shareholder.debts.associateDebt'),
    help: t('finance.shareholder.debts.associateDebtHelp'),
    value: props.ledger.shareholder_loan_debt,
    tone: 'text-critique',
    extra: '',
  },
  {
    key: 'receivable',
    icon: 'coins' as const,
    label: t('finance.shareholder.debts.receivable'),
    help: t('finance.shareholder.debts.receivableHelp'),
    value: props.ledger.shareholder_loan_receivable,
    tone: 'text-livre',
    extra: '',
  },
])

function kindLabel(kind: Line['kind']): string {
  return t(`finance.shareholder.debts.kind.${kind}`)
}

function kindVariant(kind: Line['kind']) {
  if (kind === 'receivable') return 'livre' as const
  if (kind === 'company') return 'ecart' as const
  return 'transit' as const
}

function repaymentLabel(line: Line, r: ShareholderLoanRepayment): string {
  if (r.method === 'PROFIT_SHARE') {
    return t('finance.shareholder.advance.history.deducted', {
      period: r.distribution_period ?? '',
    })
  }
  if (r.method === 'CANCEL') return t('finance.shareholder.advance.history.cancelled')
  if (r.method === 'TREASURY') {
    return t('finance.shareholder.advance.history.treasury', { account: r.account_name ?? '—' })
  }
  return line.kind === 'receivable'
    ? t('finance.shareholder.debts.repaidToYou', { name: line.counterpart })
    : t('finance.shareholder.advance.history.direct', { name: line.counterpart })
}
</script>

<template>
  <section data-test="ledger-debts" class="border-ligne mb-5 rounded-xl border p-4">
    <h3 class="text-texte mb-3 font-semibold">{{ t('finance.shareholder.debts.title') }}</h3>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-3">
      <div
        v-for="card in cards"
        :key="card.key"
        :data-test="`debt-card-${card.key}`"
        class="rounded-xl border p-4"
        :class="Number(card.value) > 0 ? 'border-ligne-forte bg-white' : 'border-ligne bg-sable/40'"
      >
        <p class="text-texte-2 flex items-center gap-2 text-xs">
          <Icon :name="card.icon" :size="14" />{{ card.label }}
        </p>
        <MonoValue
          class="text-lg font-semibold"
          align="left"
          :class="Number(card.value) > 0 ? card.tone : 'text-texte-3'"
          :value="formatMoney(card.value)"
        />
        <p class="text-texte-3 mt-1 text-xs leading-snug">{{ card.help }}</p>
        <p
          v-if="card.extra"
          :data-test="`debt-card-${card.key}-extra`"
          class="text-texte mt-1 text-xs font-medium"
        >
          {{ card.extra }}
        </p>
      </div>
    </div>

    <div class="mt-4 space-y-2">
      <article
        v-for="line in lines"
        :key="line.key"
        :data-test="`ledger-advance-${line.key}`"
        class="border-ligne rounded-lg border bg-white p-3"
      >
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div class="flex flex-wrap items-center gap-2">
              <Badge :variant="kindVariant(line.kind)">{{ kindLabel(line.kind) }}</Badge>
              <span class="text-texte text-sm font-medium">{{ line.counterpart }}</span>
            </div>
            <p class="text-texte-3 mt-1 text-xs">
              {{ line.loan.date }} ·
              {{ t(`finance.shareholder.loan.statusValues.${line.loan.status}`) }}
              <template v-if="line.loan.notes"> · {{ line.loan.notes }}</template>
            </p>
            <p v-if="line.kind === 'company'" class="text-texte-2 mt-0.5 text-xs">
              {{ t('finance.shareholder.advance.drawn') }} :
              <MonoValue class="inline" :value="formatMoney(line.loan.amount_drawn)" />
              · {{ t('finance.shareholder.advance.undrawn') }} :
              <MonoValue class="inline" :value="formatMoney(line.loan.undrawn_amount)" />
            </p>
          </div>
          <div class="text-end text-sm">
            <MonoValue :value="formatMoney(line.loan.amount)" />
            <p class="text-texte-2 text-xs">
              {{ t('finance.shareholder.loan.remaining') }} :
              <MonoValue
                class="inline font-semibold"
                :class="Number(line.loan.remaining_amount) > 0 ? 'text-texte' : 'text-texte-3'"
                :value="formatMoney(line.loan.remaining_amount)"
              />
            </p>
          </div>
        </div>
        <ul v-if="line.loan.repayments.length" class="border-ligne mt-2 space-y-1 border-t pt-2">
          <li
            v-for="r in line.loan.repayments"
            :key="r.id"
            class="text-texte-2 flex flex-wrap justify-between gap-2 text-xs"
          >
            <span>{{ r.date }} · {{ repaymentLabel(line, r) }}</span>
            <MonoValue :value="formatMoney(r.amount)" />
          </li>
        </ul>
      </article>
      <p v-if="lines.length === 0" class="text-texte-3 py-3 text-center text-sm">
        {{ t('finance.shareholder.debts.empty') }}
      </p>
    </div>
  </section>
</template>
