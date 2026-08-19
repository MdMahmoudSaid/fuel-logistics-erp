<script setup lang="ts">
// docs/PHASE_5_PLAN.md Etape 10: global treasury journal
// (GET /api/treasury-transactions/), with a shortcut into the internal
// transfer form.
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { treasuryTransactionResource } from './api'
import type { TreasuryTransaction } from './types'

const router = useRouter()

const transactions = ref<TreasuryTransaction[]>([])
const loading = ref(true)
const error = ref('')

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
    const [txnData, bankData, cashData] = await Promise.all([
      treasuryTransactionResource.list(),
      bankAccountResource.list(),
      cashAccountResource.list(),
    ])
    transactions.value = txnData.results
    bankAccounts.value = bankData.results
    cashAccounts.value = cashData.results
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
      <h2 class="text-lg font-semibold text-slate-800">Treasury Journal</h2>
      <button
        class="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white"
        @click="router.push({ name: 'treasury-transfer' })"
      >
        Internal transfer
      </button>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">Loading…</p>

    <section v-else class="rounded border bg-white p-4">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-b text-slate-500">
            <th class="px-2 py-1.5 font-medium">Date</th>
            <th class="px-2 py-1.5 font-medium">Type</th>
            <th class="px-2 py-1.5 font-medium">Account</th>
            <th class="px-2 py-1.5 font-medium">Reference</th>
            <th class="px-2 py-1.5 font-medium text-right">Amount</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="txn in transactions" :key="txn.id" class="border-b last:border-0">
            <td class="px-2 py-1.5">{{ txn.date }}</td>
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
            <td class="px-2 py-1.5 text-right font-medium text-slate-800">
              {{ Number(txn.amount).toLocaleString() }}
            </td>
          </tr>
          <tr v-if="transactions.length === 0">
            <td colspan="5" class="px-2 py-4 text-center text-slate-400">No transactions yet.</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
