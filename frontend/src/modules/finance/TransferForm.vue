<script setup lang="ts">
// docs/PHASE_5_PLAN.md Etape 10: internal transfer between two treasury
// accounts. Posts to TreasuryService.record_transfer() via
// POST /api/treasury-transactions/transfer/, which creates the matched
// MONEY_OUT/MONEY_IN TRANSFER pair atomically (guide Section 8.10/D).
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { recordTransfer } from './api'

const router = useRouter()

const bankAccountResource = createResourceApi<{ id: number; name: string }>('/bank-accounts/')
const cashAccountResource = createResourceApi<{ id: number; name: string }>('/cash-accounts/')
const bankAccounts = ref<{ id: number; name: string }[]>([])
const cashAccounts = ref<{ id: number; name: string }[]>([])

onMounted(async () => {
  const [bankData, cashData] = await Promise.all([
    bankAccountResource.list(),
    cashAccountResource.list(),
  ])
  bankAccounts.value = bankData.results
  cashAccounts.value = cashData.results
})

const form = ref({
  source_account_type: 'bank' as 'bank' | 'cash',
  source_account_id: '',
  dest_account_type: 'cash' as 'bank' | 'cash',
  dest_account_id: '',
  amount: '',
  date: new Date().toISOString().slice(0, 10),
  reference: '',
})

function optionsFor(type: 'bank' | 'cash') {
  return type === 'bank' ? bankAccounts.value : cashAccounts.value
}
const sourceOptions = computed(() => optionsFor(form.value.source_account_type))
const destOptions = computed(() => optionsFor(form.value.dest_account_type))

const sameAccount = computed(
  () =>
    form.value.source_account_type === form.value.dest_account_type &&
    form.value.source_account_id !== '' &&
    form.value.source_account_id === form.value.dest_account_id,
)

const saving = ref(false)
const error = ref('')

async function onSubmit() {
  saving.value = true
  error.value = ''
  try {
    await recordTransfer({
      source_account_type: form.value.source_account_type,
      source_account_id: Number(form.value.source_account_id),
      dest_account_type: form.value.dest_account_type,
      dest_account_id: Number(form.value.dest_account_id),
      amount: form.value.amount,
      date: form.value.date,
      reference: form.value.reference,
    })
    router.push({ name: 'treasury-transactions' })
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail || 'Could not record this transfer.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="max-w-xl space-y-6">
    <h2 class="text-lg font-semibold text-slate-800">Internal Transfer</h2>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-if="sameAccount" class="text-sm text-red-600">
      Source and destination cannot be the same account.
    </p>

    <form class="space-y-4 rounded border bg-white p-4" @submit.prevent="onSubmit">
      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="source_type"
            >From account type</label
          >
          <select
            id="source_type"
            v-model="form.source_account_type"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="bank">Bank</option>
            <option value="cash">Cash</option>
          </select>
        </div>
        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="source_id">From account</label>
          <select
            id="source_id"
            v-model="form.source_account_id"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="" disabled>Select an account</option>
            <option v-for="a in sourceOptions" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="dest_type">To account type</label>
          <select
            id="dest_type"
            v-model="form.dest_account_type"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="bank">Bank</option>
            <option value="cash">Cash</option>
          </select>
        </div>
        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="dest_id">To account</label>
          <select
            id="dest_id"
            v-model="form.dest_account_id"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="" disabled>Select an account</option>
            <option v-for="a in destOptions" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="amount">Amount</label>
          <input
            id="amount"
            v-model="form.amount"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="date">Date</label>
          <input
            id="date"
            v-model="form.date"
            type="date"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div class="col-span-2 space-y-1">
          <label class="text-sm font-medium text-slate-600" for="reference">Reference</label>
          <input
            id="reference"
            v-model="form.reference"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
      </div>

      <div class="flex justify-end">
        <button
          type="submit"
          :disabled="saving || sameAccount"
          class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {{ saving ? 'Transferring…' : 'Transfer' }}
        </button>
      </div>
    </form>
  </div>
</template>
