<script setup lang="ts">
// docs/PHASE_5_PLAN.md Etape 10: internal transfer between two treasury
// accounts. Posts to TreasuryService.record_transfer() via
// POST /api/treasury-transactions/transfer/, which creates the matched
// MONEY_OUT/MONEY_IN TRANSFER pair atomically (guide Section 8.10/D).
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import { translateApiError } from '@/i18n/apiErrors'
import { recordTransfer } from './api'
import Button from '@/components/ui/Button.vue'

const emit = defineEmits<{ success: []; cancel: [] }>()
const { t } = useI18n()

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
    emit('success')
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = translateApiError(detail) || t('finance.transfer.saveError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-if="sameAccount" class="text-critique text-sm">
      {{ t('finance.transfer.sameAccountError') }}
    </p>

    <form
      class="border-ligne space-y-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="source_type">{{
            t('finance.transfer.fromAccountType')
          }}</label>
          <select
            id="source_type"
            v-model="form.source_account_type"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="bank">{{ t('finance.transfer.bank') }}</option>
            <option value="cash">{{ t('finance.transfer.cash') }}</option>
          </select>
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="source_id">{{
            t('finance.transfer.fromAccount')
          }}</label>
          <select
            id="source_id"
            v-model="form.source_account_id"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.transfer.selectAccount') }}</option>
            <option v-for="a in sourceOptions" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="dest_type">{{
            t('finance.transfer.toAccountType')
          }}</label>
          <select
            id="dest_type"
            v-model="form.dest_account_type"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="bank">{{ t('finance.transfer.bank') }}</option>
            <option value="cash">{{ t('finance.transfer.cash') }}</option>
          </select>
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="dest_id">{{
            t('finance.transfer.toAccount')
          }}</label>
          <select
            id="dest_id"
            v-model="form.dest_account_id"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.transfer.selectAccount') }}</option>
            <option v-for="a in destOptions" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="amount">{{
            t('finance.transfer.amount')
          }}</label>
          <input
            id="amount"
            v-model="form.amount"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="date">{{
            t('finance.transfer.date')
          }}</label>
          <input
            id="date"
            v-model="form.date"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>

        <div class="col-span-2 space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="reference">{{
            t('finance.transfer.reference')
          }}</label>
          <input
            id="reference"
            v-model="form.reference"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
      </div>

      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('cancel')">
          {{ t('common.cancel') }}
        </Button>
        <Button type="submit" variant="primary" :disabled="sameAccount" :loading="saving">
          {{ saving ? t('finance.transfer.transferring') : t('finance.transfer.transfer') }}
        </Button>
      </div>
    </form>
  </div>
</template>
