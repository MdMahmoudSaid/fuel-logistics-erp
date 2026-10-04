<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppAlert from '@/components/ui/AppAlert.vue'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { formatMoney } from '@/utils/currency'
import { translateApiError } from '@/i18n/apiErrors'
import { allocateExistingCustomerPayment } from './api'
import type { CustomerLedgerInvoice, CustomerPayment } from './types'

const props = defineProps<{
  payment: CustomerPayment
  invoices: CustomerLedgerInvoice[]
}>()
const emit = defineEmits<{ success: []; cancel: [] }>()
const { t } = useI18n()

const eligibleInvoices = computed(() =>
  [...props.invoices]
    .filter(
      (invoice) =>
        Number(invoice.outstanding) > 0 &&
        (invoice.status === 'VALIDATED' || invoice.status === 'PARTIALLY_PAID'),
    )
    .sort((a, b) =>
      a.issued_date === b.issued_date ? a.id - b.id : a.issued_date.localeCompare(b.issued_date),
    ),
)

function fifoAmounts(): Record<number, string> {
  let remaining = Number(props.payment.unallocated_amount)
  const values: Record<number, string> = {}
  for (const invoice of eligibleInvoices.value) {
    const amount = Math.min(remaining, Number(invoice.outstanding))
    values[invoice.id] = amount > 0 ? amount.toFixed(2) : ''
    remaining -= amount
  }
  return values
}

const amounts = ref<Record<number, string>>(fifoAmounts())
const saving = ref(false)
const error = ref('')
const allocatedTotal = computed(() =>
  Object.values(amounts.value).reduce((sum, amount) => sum + (Number(amount) || 0), 0),
)
const exceedsCredit = computed(
  () => allocatedTotal.value - Number(props.payment.unallocated_amount) > 0.001,
)

async function submit() {
  const allocations = eligibleInvoices.value
    .filter((invoice) => Number(amounts.value[invoice.id]) > 0)
    .map((invoice) => ({ invoice: invoice.id, amount: amounts.value[invoice.id] }))
  if (allocations.length === 0 || exceedsCredit.value) return

  saving.value = true
  error.value = ''
  try {
    await allocateExistingCustomerPayment(props.payment.id, allocations)
    emit('success')
  } catch (cause) {
    const detail = (cause as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = translateApiError(detail) || t('finance.customerLedger.allocation.saveError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="space-y-4" @submit.prevent="submit">
    <AppAlert v-if="error" :message="error" />
    <div class="border-ligne rounded-lg border bg-surface p-4">
      <p class="text-texte-2 text-xs font-semibold uppercase">
        {{ t('finance.customerLedger.allocation.availableCredit') }}
      </p>
      <MonoValue
        class="text-livre mt-1 font-semibold"
        align="left"
        :value="formatMoney(payment.unallocated_amount)"
      />
      <p class="text-texte-2 mt-2 text-sm">
        {{ t('finance.customerLedger.allocation.explanation') }}
      </p>
    </div>

    <div v-if="eligibleInvoices.length" class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-2 py-2 text-start font-medium">
              {{ t('finance.customerLedger.table.invoice') }}
            </th>
            <th class="px-2 py-2 text-end font-medium">
              {{ t('finance.customerLedger.table.outstanding') }}
            </th>
            <th class="px-2 py-2 text-end font-medium">
              {{ t('finance.customerLedger.allocation.amountToApply') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="invoice in eligibleInvoices" :key="invoice.id" class="border-ligne border-b">
            <td class="px-2 py-2">{{ invoice.invoice_number }}</td>
            <td class="px-2 py-2 text-end">{{ formatMoney(invoice.outstanding) }}</td>
            <td class="px-2 py-2 text-end">
              <input
                v-model="amounts[invoice.id]"
                :data-test="`allocation-amount-${invoice.id}`"
                type="number"
                min="0"
                :max="invoice.outstanding"
                step="0.01"
                class="border-ligne-forte h-10 w-40 rounded-lg border bg-white px-3 text-end"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <AppAlert
      v-else
      :message="t('finance.customerLedger.allocation.noOpenInvoices')"
      variant="warning"
    />

    <div class="flex items-center justify-between gap-3">
      <div>
        <span class="text-texte-2 text-sm"
          >{{ t('finance.customerLedger.allocation.total') }}:
        </span>
        <MonoValue class="inline font-semibold" :value="formatMoney(allocatedTotal)" />
        <p v-if="exceedsCredit" class="text-critique text-sm">
          {{ t('finance.customerLedger.allocation.exceedsCredit') }}
        </p>
      </div>
      <div class="flex gap-2">
        <Button variant="ghost" @click="emit('cancel')">{{ t('common.cancel') }}</Button>
        <Button
          type="submit"
          :loading="saving"
          :disabled="eligibleInvoices.length === 0 || allocatedTotal <= 0 || exceedsCredit"
          data-test="submit-existing-allocation"
        >
          {{ t('finance.customerLedger.allocation.apply') }}
        </Button>
      </div>
    </div>
  </form>
</template>
