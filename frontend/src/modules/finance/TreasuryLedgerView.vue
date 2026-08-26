<script setup lang="ts">
// docs/PHASE_5_PLAN.md Etape 10: global treasury journal
// (GET /api/treasury-transactions/), with a shortcut into the internal
// transfer form.
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { treasuryTransactionResource } from './api'
import { fetchDashboardSummary } from '@/modules/dashboard/api'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import Modal from '@/components/ui/Modal.vue'
import TransferForm from './TransferForm.vue'
import DebtPaymentForm from './DebtPaymentForm.vue'
import type { TreasuryTransaction } from './types'
import { formatMoney } from '@/utils/currency'

const route = useRoute()
const { t } = useI18n()

const showTransferModal = ref(false)
const showDebtPaymentModal = ref(false)
const previewUrl = ref<string | null>(null)

const IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp']

function isImageUrl(url: string): boolean {
  const path = url.split('?')[0].toLowerCase()
  return IMAGE_EXTENSIONS.some((ext) => path.endsWith(ext))
}

function onTransferSuccess() {
  showTransferModal.value = false
  load()
}

function onDebtPaymentSuccess() {
  showDebtPaymentModal.value = false
  load()
}

const transactions = ref<TreasuryTransaction[]>([])
const loading = ref(true)
const error = ref('')

// §0.3/Etape 6.3 : solde courant global (pas borné par une période - c'est
// une balance, pas un flux), déjà calculé par le dashboard summary
// (backend/apps/reports/views/dashboard.py) à partir de tous les comptes.
const balance = ref<number | null>(null)

function accountLabel(txn: TreasuryTransaction): string {
  return txn.bank_account_name ?? txn.cash_account_name ?? '—'
}

// "Source ou beneficiaire" (docs/edit.md UI pass 2026-08-26, Journal de
// tresorerie): the resolved counterparty when available, else a plain
// fallback so the row never reads as a bare, unexplained movement.
function sourceLabel(txn: TreasuryTransaction): string {
  if (txn.counterparty) return txn.counterparty
  return txn.is_transfer
    ? t('transactionType.TRANSFER')
    : t(`transactionType.${txn.type}`)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [txnData, summary] = await Promise.all([
      treasuryTransactionResource.list(),
      fetchDashboardSummary({}),
    ])
    transactions.value = txnData.results
    balance.value = Number(summary.finance.treasury_balance)
  } catch {
    error.value = t('finance.treasuryLedger.loadError')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  if (route.query.action === 'transfer') showTransferModal.value = true
  if (route.query.action === 'payment') showDebtPaymentModal.value = true
})

const TYPE_BADGE: Record<string, string> = {
  MONEY_IN: 'bg-emerald-100 text-emerald-700',
  MONEY_OUT: 'bg-red-100 text-red-700',
}
</script>

<template>
  <div class="max-w-7xl space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('finance.treasuryLedger.title') }}
      </h1>
      <div class="flex gap-2">
        <Button variant="primary" @click="showDebtPaymentModal = true">
          {{ t('finance.treasuryLedger.newPayment') }}
        </Button>
      </div>
    </div>

    <!-- Solde courant — §0.3 : Mono 30px sur carte bitume, négatif en
         --critique sans parenthèses. -->
    <div v-if="balance !== null" class="bg-bitume rounded-xl p-5">
      <p class="text-sable/60 text-xs font-medium uppercase">
        {{ t('finance.treasuryLedger.currentBalance') }}
      </p>
      <p
        class="font-mono text-[30px] leading-none font-semibold tabular-nums"
        :class="balance < 0 ? 'text-critique' : 'text-sable'"
      >
        {{ balance < 0 ? '−' : '' }}{{ formatMoney(Math.abs(balance)) }}
      </p>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">{{ t('common.loading') }}</p>

    <section v-else class="border-ligne overflow-x-auto rounded-xl border bg-white p-4">
      <table class="w-full text-start text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-2 py-1.5 font-medium">{{ t('finance.treasuryLedger.table.date') }}</th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.treasuryLedger.table.type') }}</th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.treasuryLedger.table.source') }}</th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.treasuryLedger.table.account') }}</th>
            <th class="px-2 py-1.5 font-medium">
              {{ t('finance.treasuryLedger.table.reference') }}
            </th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.treasuryLedger.table.note') }}</th>
            <th class="px-2 py-1.5 text-end font-medium">
              {{ t('finance.treasuryLedger.table.amount') }}
            </th>
            <th class="px-2 py-1.5 font-medium">
              {{ t('finance.treasuryLedger.table.attachment') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="txn in transactions" :key="txn.id" class="border-ligne border-b last:border-0">
            <td class="px-2 py-1.5 whitespace-nowrap">
              <MonoValue :value="txn.date" align="left" />
            </td>
            <td class="px-2 py-1.5 whitespace-nowrap">
              <span
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :class="TYPE_BADGE[txn.type]"
              >
                {{ t(`transactionType.${txn.type}`) }}
              </span>
              <span
                v-if="txn.is_transfer"
                class="ms-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600"
              >
                {{ t('transactionType.TRANSFER') }}
              </span>
            </td>
            <td class="px-2 py-1.5">{{ sourceLabel(txn) }}</td>
            <td class="px-2 py-1.5 whitespace-nowrap">{{ accountLabel(txn) }}</td>
            <td class="px-2 py-1.5 whitespace-nowrap">{{ txn.reference || '—' }}</td>
            <td class="px-2 py-1.5">{{ txn.note || '—' }}</td>
            <td class="px-2 py-1.5 text-end whitespace-nowrap">
              <MonoValue
                :value="(txn.type === 'MONEY_OUT' ? '−' : '') + formatMoney(txn.amount)"
                :class="txn.type === 'MONEY_OUT' ? 'text-critique' : 'text-texte'"
              />
            </td>
            <td class="px-2 py-1.5 whitespace-nowrap">
              <button
                v-if="txn.document_url"
                type="button"
                class="text-bitume underline"
                @click="previewUrl = txn.document_url"
              >
                {{ t('finance.treasuryLedger.table.attachment') }}
              </button>
              <span v-else class="text-texte-3">—</span>
            </td>
          </tr>
          <tr v-if="transactions.length === 0">
            <td colspan="8" class="text-texte-3 px-2 py-4 text-center">
              {{ t('finance.treasuryLedger.noTransactions') }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <Modal
      v-if="showTransferModal"
      :title="t('finance.transfer.title')"
      max-width="max-w-xl"
      @close="showTransferModal = false"
    >
      <TransferForm @success="onTransferSuccess" @cancel="showTransferModal = false" />
    </Modal>

    <Modal
      v-if="showDebtPaymentModal"
      :title="t('finance.debtPayment.title')"
      max-width="max-w-2xl"
      @close="showDebtPaymentModal = false"
    >
      <DebtPaymentForm @success="onDebtPaymentSuccess" @cancel="showDebtPaymentModal = false" />
    </Modal>

    <Modal
      v-if="previewUrl"
      :title="t('finance.treasuryLedger.table.attachment')"
      max-width="max-w-3xl"
      @close="previewUrl = null"
    >
      <img
        v-if="isImageUrl(previewUrl)"
        :src="previewUrl"
        class="max-h-[80vh] w-full rounded-lg object-contain"
      />
      <iframe v-else :src="previewUrl" class="h-[80vh] w-full rounded-lg" />
    </Modal>
  </div>
</template>
