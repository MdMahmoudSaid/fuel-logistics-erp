<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// Client modification Task 5: supplier debt repayment must move through a
// bank account by bank transfer - no cash settlement for that flow
// (backend/apps/finance/serializers.py SupplierPaymentSerializer.validate()
// rejects anything else for is_advance=False). Opened from
// SupplierLedgerView.vue (supplier-scoped, not trip-scoped) - the outstanding
// balance shown here is the same ledger.outstanding_balance that view
// already fetches, passed in as a prop rather than fetched a second time.
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import { translateApiError } from '@/i18n/apiErrors'
import { supplierPaymentResource } from './api'
import Button from '@/components/ui/Button.vue'
import { formatMoney } from '@/utils/currency'

const props = defineProps<{
  supplierId: number
  supplierName: string
  outstandingBalance: string
}>()
const emit = defineEmits<{ success: []; cancel: [] }>()
const { t } = useI18n()

const bankAccountResource = createResourceApi<{ id: number; name: string }>('/bank-accounts/')
const bankAccounts = ref<{ id: number; name: string }[]>([])

const amount = ref('')
const paymentDate = ref(new Date().toISOString().slice(0, 10))
const bankAccount = ref('')

const saving = ref(false)
const error = ref('')

onMounted(async () => {
  const bankData = await bankAccountResource.list()
  bankAccounts.value = bankData.results
})

async function onSubmit() {
  saving.value = true
  error.value = ''
  try {
    await supplierPaymentResource.create({
      supplier: props.supplierId,
      // Vue 3.4+ auto-casts v-model on <input type="number"> to a JS
      // number - cast back to a string so the payload matches the
      // DecimalField-backed API contract exactly (never send a float).
      amount: String(amount.value),
      payment_date: paymentDate.value,
      // Supplier debt repayment is bank-transfer-only server-side (no method
      // selector shown to the user - it's always this).
      method: 'BANK_TRANSFER',
      bank_account: Number(bankAccount.value),
      is_advance: false,
    })
    emit('success')
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = translateApiError(detail) || t('finance.supplierPayment.saveError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <AppAlert v-if="error" :message="error" />

    <form
      class="border-ligne space-y-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <h2 class="font-display text-sm font-semibold uppercase">
        {{ t('finance.supplierPayment.title') }}
      </h2>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.supplierPayment.supplier')
          }}</span>
          <p class="text-texte h-12 flex items-center">{{ supplierName }}</p>
        </div>

        <div class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.supplierPayment.outstandingBalance')
          }}</span>
          <p class="text-texte h-12 flex items-center font-semibold">
            {{ formatMoney(outstandingBalance) }}
          </p>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="supplier_payment_amount">{{
            t('finance.supplierPayment.amount')
          }}</label>
          <input
            id="supplier_payment_amount"
            v-model="amount"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="supplier_payment_date">{{
            t('finance.supplierPayment.paymentDate')
          }}</label>
          <input
            id="supplier_payment_date"
            v-model="paymentDate"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>

        <div class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.supplierPayment.method')
          }}</span>
          <p class="text-texte h-12 flex items-center">
            {{ t('paymentMethod.BANK_TRANSFER') }}
          </p>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="supplier_payment_bank_account">{{
            t('finance.supplierPayment.bankAccount')
          }}</label>
          <select
            id="supplier_payment_bank_account"
            v-model="bankAccount"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.supplierPayment.selectBankAccount') }}</option>
            <option v-for="account in bankAccounts" :key="account.id" :value="account.id">
              {{ account.name }}
            </option>
          </select>
        </div>
      </div>

      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('cancel')">
          {{ t('common.cancel') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('finance.supplierPayment.saving') : t('finance.supplierPayment.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>
