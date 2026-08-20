<script setup lang="ts">
// docs/PHASE_5_PLAN.md Etape 10: global treasury journal
// (GET /api/treasury-transactions/), with a shortcut into the internal
// transfer form.
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { treasuryTransactionResource } from './api'
import { fetchDashboardSummary } from '@/modules/dashboard/api'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import type { TreasuryTransaction } from './types'

const router = useRouter()

const transactions = ref<TreasuryTransaction[]>([])
const loading = ref(true)
const error = ref('')

// §0.3/Etape 6.3 : solde courant global (pas borné par une période - c'est
// une balance, pas un flux), déjà calculé par le dashboard summary
// (backend/apps/reports/views/dashboard.py) à partir de tous les comptes.
const balance = ref<number | null>(null)

const bankAccountResource = createResourceApi<{ id: number; name: string }>('/bank-accounts/')
const cashAccountResource = createResourceApi<{ id: number; name: string }>('/cash-accounts/')
const bankAccounts = ref<{ id: number; name: string }[]>([])
const cashAccounts = ref<{ id: number; name: string }[]>([])

function accountLabel(txn: TreasuryTransaction): string {
  if (txn.bank_account) {
    return (
      bankAccounts.value.find((a) => a.id === txn.bank_account)?.name ?? `Bank #${txn.bank_account}`
    )
  }
  if (txn.cash_account) {
    return (
      cashAccounts.value.find((a) => a.id === txn.cash_account)?.name ?? `Cash #${txn.cash_account}`
    )
  }
  return '—'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [txnData, bankData, cashData, summary] = await Promise.all([
      treasuryTransactionResource.list(),
      bankAccountResource.list(),
      cashAccountResource.list(),
      fetchDashboardSummary({}),
    ])
    transactions.value = txnData.results
    bankAccounts.value = bankData.results
    cashAccounts.value = cashData.results
    balance.value = Number(summary.finance.treasury_balance)
  } catch {
    error.value = 'Could not load the treasury journal.'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const TYPE_BADGE: Record<string, string> = {
  MONEY_IN: 'bg-emerald-100 text-emerald-700',
  MONEY_OUT: 'bg-red-100 text-red-700',
}
</script>

<template>
  <div class="max-w-4xl space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">Treasury Journal</h1>
      <Button variant="primary" @click="router.push({ name: 'treasury-transfer' })">
        Internal transfer
      </Button>
    </div>

    <!-- Solde courant — §0.3 : Mono 30px sur carte bitume, négatif en
         --critique sans parenthèses. -->
    <div v-if="balance !== null" class="bg-bitume rounded-xl p-5">
      <p class="text-sable/60 text-xs font-medium uppercase">Solde courant</p>
      <p
        class="font-mono text-[30px] leading-none font-semibold tabular-nums"
        :class="balance < 0 ? 'text-critique' : 'text-sable'"
      >
        {{ balance < 0 ? '−' : '' }}{{ Math.abs(balance).toLocaleString() }}
      </p>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">Loading…</p>

    <section v-else class="border-ligne rounded-xl border bg-white p-4">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-2 py-1.5 font-medium">Date</th>
            <th class="px-2 py-1.5 font-medium">Type</th>
            <th class="px-2 py-1.5 font-medium">Account</th>
            <th class="px-2 py-1.5 font-medium">Reference</th>
            <th class="px-2 py-1.5 text-right font-medium">Amount</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="txn in transactions" :key="txn.id" class="border-ligne border-b last:border-0">
            <td class="px-2 py-1.5"><MonoValue :value="txn.date" align="left" /></td>
            <td class="px-2 py-1.5">
              <span
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :class="TYPE_BADGE[txn.type]"
              >
                {{ txn.type }}
              </span>
              <span
                v-if="txn.is_transfer"
                class="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600"
              >
                TRANSFER
              </span>
            </td>
            <td class="px-2 py-1.5">{{ accountLabel(txn) }}</td>
            <td class="px-2 py-1.5">{{ txn.reference || '—' }}</td>
            <td class="px-2 py-1.5 text-right">
              <MonoValue
                :value="(txn.type === 'MONEY_OUT' ? '−' : '') + Number(txn.amount).toLocaleString()"
                :class="txn.type === 'MONEY_OUT' ? 'text-critique' : 'text-texte'"
              />
            </td>
          </tr>
          <tr v-if="transactions.length === 0">
            <td colspan="5" class="text-texte-3 px-2 py-4 text-center">No transactions yet.</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
