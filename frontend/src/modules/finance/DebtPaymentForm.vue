<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { fetchPayableDebts, recordDebtPayment } from './api'
import type { DebtPaymentType, PayableDebt } from './types'
import { formatMoney } from '@/utils/currency'
import { IMAGE_UPLOAD_ACCEPT, isAllowedImageFile } from '@/utils/imageUpload'

const emit = defineEmits<{
  success: []
  cancel: []
}>()

const props = withDefaults(
  defineProps<{
    initialDebtType?: DebtPaymentType
    initialDebtId?: number | null
    lockDebtType?: boolean
    lockDebt?: boolean
  }>(),
  {
    initialDebtType: 'supplier',
    initialDebtId: null,
    lockDebtType: false,
    lockDebt: false,
  },
)

const { t } = useI18n()

interface BankOption {
  id: number
  name: string
  current_balance: string
}

const DEBT_TYPES: { value: DebtPaymentType; labelKey: string }[] = [
  { value: 'supplier', labelKey: 'finance.debtPayment.types.supplier' },
  { value: 'transporter', labelKey: 'finance.debtPayment.types.transporter' },
  { value: 'customs', labelKey: 'finance.debtPayment.types.customs' },
  { value: 'transit', labelKey: 'finance.debtPayment.types.transit' },
  { value: 'road_transit', labelKey: 'finance.debtPayment.types.roadTransit' },
  { value: 'border', labelKey: 'finance.debtPayment.types.border' },
  { value: 'loading', labelKey: 'finance.debtPayment.types.loading' },
]

const bankAccountResource = createResourceApi<BankOption>('/bank-accounts/')

const debtType = ref<DebtPaymentType>(props.initialDebtType)
const debtId = ref('')
const bankAccountId = ref('')
const amount = ref('')
const reference = ref('')
const note = ref('')
const attachment = ref<File | null>(null)
const attachmentError = ref('')
const date = ref(new Date().toISOString().slice(0, 10))

function onAttachmentChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (file && !isAllowedImageFile(file)) {
    attachment.value = null
    input.value = ''
    attachmentError.value = t('finance.debtPayment.imageOnlyError')
    return
  }
  attachment.value = file
  attachmentError.value = ''
}
const debts = ref<PayableDebt[]>([])
const banks = ref<BankOption[]>([])
const loading = ref(true)
const debtLoading = ref(false)
const saving = ref(false)
const error = ref('')
const emptyDebtMessage = ref('')

const selectedDebt = computed(
  () => debts.value.find((debt) => debt.id === Number(debtId.value)) ?? null,
)
const selectedBank = computed(
  () => banks.value.find((bank) => bank.id === Number(bankAccountId.value)) ?? null,
)
const amountNumber = computed(() => Number(amount.value || 0))
const remainingAfterPayment = computed(() => {
  if (!selectedDebt.value) return 0
  return Number(selectedDebt.value.remaining_amount) - amountNumber.value
})

async function loadDebts() {
  debtLoading.value = true
  error.value = ''
  emptyDebtMessage.value = ''
  debtId.value = ''
  try {
    const fetched = await fetchPayableDebts(debtType.value)
    if (props.lockDebt) {
      // Locked to a specific entity (e.g. opened from a transporter's own
      // ledger page): never let a missing match silently fall back to
      // another entity's debt, and never expose other entities in the list.
      const lockedDebt = fetched.find((debt) => debt.id === props.initialDebtId)
      debts.value = lockedDebt ? [lockedDebt] : []
      debtId.value = lockedDebt ? String(lockedDebt.id) : ''
      if (!lockedDebt) {
        error.value = t('finance.debtPayment.errors.debtNotFound')
      }
    } else {
      debts.value = fetched
      const initialDebt = debts.value.find((debt) => debt.id === props.initialDebtId)
      debtId.value = initialDebt
        ? String(initialDebt.id)
        : debts.value[0]
          ? String(debts.value[0].id)
          : ''
      if (!debts.value.length) {
        emptyDebtMessage.value = t('finance.debtPayment.errors.noOpenDebts')
      }
    }
  } catch {
    debts.value = []
    debtId.value = ''
    error.value = t('finance.debtPayment.loadError')
  } finally {
    debtLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [bankData] = await Promise.all([bankAccountResource.list(), loadDebts()])
    banks.value = bankData.results
    bankAccountId.value = banks.value[0]?.id ? String(banks.value[0].id) : ''
  } catch {
    error.value = t('finance.debtPayment.loadError')
  } finally {
    loading.value = false
  }
}

function validate(): boolean {
  error.value = ''
  if (!selectedDebt.value) {
    error.value = t('finance.debtPayment.errors.debtRequired')
    return false
  }
  if (!selectedBank.value) {
    error.value = t('finance.debtPayment.errors.bankRequired')
    return false
  }
  if (amountNumber.value <= 0) {
    error.value = t('finance.debtPayment.errors.positiveAmount')
    return false
  }
  if (amountNumber.value > Number(selectedDebt.value.remaining_amount)) {
    error.value = t('finance.debtPayment.errors.aboveRemaining')
    return false
  }
  if (amountNumber.value > Number(selectedBank.value.current_balance)) {
    error.value = t('finance.debtPayment.errors.insufficientBank')
    return false
  }
  // Proof upload is optional (Task 14), but a file that WAS selected and
  // rejected by onAttachmentChange (wrong type) must still block submission
  // - silently dropping it and submitting without it would be surprising.
  if (attachmentError.value) {
    return false
  }
  return true
}

async function submit() {
  if (!validate() || !selectedDebt.value || !selectedBank.value) return
  saving.value = true
  try {
    await recordDebtPayment({
      debt_type: debtType.value,
      debt_id: selectedDebt.value.id,
      bank_account: selectedBank.value.id,
      amount: amount.value,
      date: date.value,
      reference: reference.value,
      note: note.value,
      attachment: attachment.value,
    })
    emit('success')
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
    error.value = detail ?? t('finance.debtPayment.saveError')
  } finally {
    saving.value = false
  }
}

watch(debtType, loadDebts)
onMounted(load)
</script>

<template>
  <form class="space-y-5" @submit.prevent="submit">
    <AppAlert v-if="error" :message="error" />
    <p v-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else>
      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.debtPayment.type') }}</span>
          <select
            v-model="debtType"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
            :disabled="lockDebtType"
          >
            <option v-for="type in DEBT_TYPES" :key="type.value" :value="type.value">
              {{ t(type.labelKey) }}
            </option>
          </select>
        </label>

        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.debtPayment.debt') }}</span>
          <select
            id="debt"
            v-model="debtId"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
            :disabled="debtLoading || debts.length === 0 || lockDebt"
          >
            <option v-for="debt in debts" :key="debt.id" :value="String(debt.id)">
              {{ debt.label }}
            </option>
          </select>
          <span v-if="emptyDebtMessage" class="text-texte-3 block text-xs">
            {{ emptyDebtMessage }}
          </span>
        </label>
      </div>

      <div
        v-if="selectedDebt"
        class="border-ligne grid gap-3 rounded-lg border bg-white p-3 text-sm sm:grid-cols-3"
      >
        <div>
          <p class="text-texte-3 text-xs font-medium uppercase">
            {{ t('finance.debtPayment.total') }}
          </p>
          <MonoValue :value="formatMoney(selectedDebt.total_amount)" align="left" />
        </div>
        <div>
          <p class="text-texte-3 text-xs font-medium uppercase">
            {{ t('finance.debtPayment.paid') }}
          </p>
          <MonoValue :value="formatMoney(selectedDebt.paid_amount)" align="left" />
        </div>
        <div>
          <p class="text-texte-3 text-xs font-medium uppercase">
            {{ t('finance.debtPayment.remaining') }}
          </p>
          <MonoValue :value="formatMoney(selectedDebt.remaining_amount)" align="left" />
        </div>
      </div>

      <div v-if="selectedDebt?.lines?.length" class="border-ligne rounded-lg border bg-white p-3">
        <p class="text-texte-3 mb-2 text-xs font-medium uppercase">
          {{ t('finance.debtPayment.lineDetails') }}
        </p>
        <ul class="divide-ligne divide-y text-sm">
          <li
            v-for="line in selectedDebt.lines"
            :key="`${line.debt_type}-${line.id}`"
            class="grid gap-2 py-2 sm:grid-cols-[1fr_auto_auto_auto]"
          >
            <span class="text-texte font-medium">{{ line.label }}</span>
            <span class="text-texte-2">
              {{ t('finance.debtPayment.total') }}:
              <MonoValue :value="formatMoney(line.total_amount)" />
            </span>
            <span class="text-texte-2">
              {{ t('finance.debtPayment.paid') }}:
              <MonoValue :value="formatMoney(line.paid_amount)" />
            </span>
            <span class="text-texte">
              {{ t('finance.debtPayment.remaining') }}:
              <MonoValue :value="formatMoney(line.remaining_amount)" />
            </span>
          </li>
        </ul>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.debtPayment.bank') }}</span>
          <select
            v-model="bankAccountId"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          >
            <option v-for="bank in banks" :key="bank.id" :value="String(bank.id)">
              {{ bank.name }}
            </option>
          </select>
        </label>

        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.debtPayment.amount')
          }}</span>
          <input
            id="amount"
            v-model="amount"
            min="0.01"
            step="0.01"
            type="number"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          />
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.debtPayment.date') }}</span>
          <input
            v-model="date"
            type="date"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          />
        </label>
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">
            {{ t('finance.debtPayment.reference') }}
          </span>
          <input
            v-model="reference"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          />
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.debtPayment.note') }}</span>
          <textarea
            v-model="note"
            rows="2"
            class="border-ligne w-full rounded-lg border px-3 py-2 text-sm"
          />
        </label>
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">
            {{ t('finance.debtPayment.attachment') }}
          </span>
          <input
            type="file"
            :accept="IMAGE_UPLOAD_ACCEPT"
            class="border-ligne w-full rounded-lg border px-3 py-2 text-sm"
            @change="onAttachmentChange"
          />
          <span v-if="attachment" class="text-texte-2 block text-xs">{{ attachment.name }}</span>
          <AppAlert v-if="attachmentError" :message="attachmentError" />
        </label>
      </div>

      <div class="border-ligne grid gap-3 rounded-lg border bg-sable p-3 text-sm sm:grid-cols-3">
        <div>
          <p class="text-texte-3 text-xs font-medium uppercase">
            {{ t('finance.debtPayment.selectedBank') }}
          </p>
          <p class="text-texte font-medium">{{ selectedBank?.name || '—' }}</p>
        </div>
        <div>
          <p class="text-texte-3 text-xs font-medium uppercase">
            {{ t('finance.debtPayment.availableBalance') }}
          </p>
          <MonoValue
            :value="selectedBank ? formatMoney(selectedBank.current_balance) : '—'"
            align="left"
          />
        </div>
        <div>
          <p class="text-texte-3 text-xs font-medium uppercase">
            {{ t('finance.debtPayment.afterPayment') }}
          </p>
          <MonoValue
            :value="selectedDebt ? formatMoney(remainingAfterPayment) : '—'"
            align="left"
            :class="remainingAfterPayment < 0 ? 'text-critique' : 'text-texte'"
          />
        </div>
      </div>

      <div class="flex justify-end gap-2">
        <Button variant="ghost" type="button" @click="emit('cancel')">{{
          t('common.cancel')
        }}</Button>
        <Button variant="primary" type="submit" :loading="saving">
          {{ t('finance.debtPayment.submit') }}
        </Button>
      </div>
    </template>
  </form>
</template>
