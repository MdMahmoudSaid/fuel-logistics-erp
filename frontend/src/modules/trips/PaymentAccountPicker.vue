<script setup lang="ts">
// Bank/cash account chooser for a walk-in customer's full cash payment
// (direct sale popup + "Saisir la quantité reçue"). Emits a complete
// PaymentDestination, or null while the destination has no account yet.
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import type { PaymentDestination } from './api'

// Reserved server-side for destination=VERS_MOI, never an ordinary cash
// account (same filter as finance/PaymentAllocationForm.vue).
const VERS_MOI_ACCOUNT_NAME = 'Vers moi'

defineProps<{ modelValue: PaymentDestination | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: PaymentDestination | null] }>()
const { t } = useI18n()

type Account = { id: number; name: string }
const bankAccounts = ref<Account[]>([])
const cashAccounts = ref<Account[]>([])
const destination = ref<'CASH' | 'BANK'>('CASH')
const accountId = ref('')

const accounts = computed(() =>
  destination.value === 'BANK'
    ? bankAccounts.value
    : cashAccounts.value.filter((a) => a.name !== VERS_MOI_ACCOUNT_NAME),
)

onMounted(async () => {
  const [banks, cashes] = await Promise.all([
    createResourceApi<Account>('/bank-accounts/').list(),
    createResourceApi<Account>('/cash-accounts/').list(),
  ])
  bankAccounts.value = banks.results
  cashAccounts.value = cashes.results
})

watch(destination, () => {
  accountId.value = ''
})
watch([destination, accountId], () => {
  if (!accountId.value) return emit('update:modelValue', null)
  const id = Number(accountId.value)
  emit(
    'update:modelValue',
    destination.value === 'BANK'
      ? { destination: 'BANK', bank_account: id }
      : { destination: 'CASH', cash_account: id },
  )
})

const selectClass =
  'border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'
</script>

<template>
  <div class="space-y-3">
    <div class="grid gap-3 sm:grid-cols-2">
      <label class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{ t('finance.payment.destination') }}</span>
        <select v-model="destination" data-test="pay-destination" :class="selectClass">
          <option value="CASH">{{ t('finance.payment.cash') }}</option>
          <option value="BANK">{{ t('finance.payment.bank') }}</option>
        </select>
      </label>
      <label class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{
          destination === 'BANK' ? t('finance.payment.bankAccount') : t('finance.payment.cashAccount')
        }}</span>
        <select v-model="accountId" data-test="pay-account" :class="selectClass">
          <option value="" disabled>
            {{
              destination === 'BANK'
                ? t('finance.payment.selectBankAccount')
                : t('finance.payment.selectCashAccount')
            }}
          </option>
          <option v-for="a in accounts" :key="a.id" :value="String(a.id)">{{ a.name }}</option>
        </select>
      </label>
    </div>
  </div>
</template>
