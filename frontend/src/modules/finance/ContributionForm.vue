<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import Button from '@/components/ui/Button.vue'
import { createShareholderContribution, shareholderResource } from './api'
import type { Shareholder } from './types'
import { IMAGE_UPLOAD_ACCEPT, isAllowedImageFile } from '@/utils/imageUpload'

const emit = defineEmits<{
  success: []
  cancel: []
}>()

const props = withDefaults(
  defineProps<{
    initialShareholderId?: number | null
    lockShareholder?: boolean
  }>(),
  {
    initialShareholderId: null,
    lockShareholder: false,
  },
)

const { t } = useI18n()

interface AccountOption {
  id: number
  name: string
  current_balance: string
}

const bankAccountResource = createResourceApi<AccountOption>('/bank-accounts/')
const cashAccountResource = createResourceApi<AccountOption>('/cash-accounts/')

const shareholders = ref<Shareholder[]>([])
const shareholderId = ref('')
const accountKind = ref<'bank' | 'cash'>('bank')
const bankAccountId = ref('')
const cashAccountId = ref('')
const amount = ref('')
const reference = ref('')
const note = ref('')
const attachment = ref<File | null>(null)
const attachmentError = ref('')
const date = ref(new Date().toISOString().slice(0, 10))

const banks = ref<AccountOption[]>([])
const cashAccounts = ref<AccountOption[]>([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')

const selectedShareholder = computed(
  () => shareholders.value.find((s) => s.id === Number(shareholderId.value)) ?? null,
)
const selectedAccount = computed(() =>
  accountKind.value === 'bank'
    ? (banks.value.find((bank) => bank.id === Number(bankAccountId.value)) ?? null)
    : (cashAccounts.value.find((account) => account.id === Number(cashAccountId.value)) ?? null),
)
const amountNumber = computed(() => Number(amount.value || 0))

function onAttachmentChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (file && !isAllowedImageFile(file)) {
    attachment.value = null
    input.value = ''
    attachmentError.value = t('finance.contributionForm.imageOnlyError')
    return
  }
  attachment.value = file
  attachmentError.value = ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [shareholderData, bankData, cashData] = await Promise.all([
      shareholderResource.list(),
      bankAccountResource.list(),
      cashAccountResource.list(),
    ])
    shareholders.value = shareholderData.results
    banks.value = bankData.results
    cashAccounts.value = cashData.results
    bankAccountId.value = banks.value[0]?.id ? String(banks.value[0].id) : ''
    cashAccountId.value = cashAccounts.value[0]?.id ? String(cashAccounts.value[0].id) : ''

    if (props.lockShareholder && props.initialShareholderId) {
      shareholderId.value = String(props.initialShareholderId)
    } else {
      const initial = shareholders.value.find((s) => s.id === props.initialShareholderId)
      shareholderId.value = initial ? String(initial.id) : (shareholders.value[0]?.id ? String(shareholders.value[0].id) : '')
    }
  } catch {
    error.value = t('finance.contributionForm.loadError')
  } finally {
    loading.value = false
  }
}

function validate(): boolean {
  error.value = ''
  if (!selectedShareholder.value) {
    error.value = t('finance.contributionForm.errors.shareholderRequired')
    return false
  }
  if (!selectedAccount.value) {
    error.value = t('finance.contributionForm.errors.accountRequired')
    return false
  }
  if (amountNumber.value <= 0) {
    error.value = t('finance.contributionForm.errors.positiveAmount')
    return false
  }
  if (!attachment.value) {
    error.value = t('finance.contributionForm.errors.proofRequired')
    return false
  }
  return true
}

async function submit() {
  if (!validate() || !selectedShareholder.value || !selectedAccount.value || !attachment.value) return
  saving.value = true
  try {
    await createShareholderContribution({
      shareholder: selectedShareholder.value.id,
      bank_account: accountKind.value === 'bank' ? Number(bankAccountId.value) : null,
      cash_account: accountKind.value === 'cash' ? Number(cashAccountId.value) : null,
      amount: String(amount.value),
      date: date.value,
      reference: reference.value,
      notes: note.value,
      attachment: attachment.value,
    })
    emit('success')
  } catch (err: unknown) {
    const data = (err as { response?: { data?: Record<string, unknown> } }).response?.data
    const detail =
      (data?.detail as string | undefined) ??
      (Array.isArray(data?.non_field_errors) ? (data!.non_field_errors as string[])[0] : undefined)
    error.value = detail ?? t('finance.contributionForm.saveError')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <form class="space-y-5" @submit.prevent="submit">
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else>
      <label class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.shareholder') }}</span>
        <select
          id="shareholder"
          v-model="shareholderId"
          class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          :disabled="lockShareholder"
        >
          <option v-for="shareholder in shareholders" :key="shareholder.id" :value="String(shareholder.id)">
            {{ shareholder.name }}
          </option>
        </select>
      </label>

      <div class="grid gap-4 sm:grid-cols-3">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.accountKind') }}</span>
          <select v-model="accountKind" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm">
            <option value="bank">{{ t('finance.contributionForm.bank') }}</option>
            <option value="cash">{{ t('finance.contributionForm.cash') }}</option>
          </select>
        </label>
        <label v-if="accountKind === 'bank'" class="space-y-1.5 sm:col-span-2">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.bank') }}</span>
          <select v-model="bankAccountId" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm">
            <option v-for="bank in banks" :key="bank.id" :value="String(bank.id)">{{ bank.name }}</option>
          </select>
        </label>
        <label v-else class="space-y-1.5 sm:col-span-2">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.cash') }}</span>
          <select v-model="cashAccountId" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm">
            <option v-for="account in cashAccounts" :key="account.id" :value="String(account.id)">
              {{ account.name }}
            </option>
          </select>
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.amount') }}</span>
          <input
            id="amount"
            v-model="amount"
            min="0.01"
            step="0.01"
            type="number"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          />
        </label>
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.date') }}</span>
          <input v-model="date" type="date" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm" />
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.reference') }}</span>
          <input v-model="reference" class="border-ligne h-11 w-full rounded-lg border px-3 text-sm" />
        </label>
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.note') }}</span>
          <textarea v-model="note" rows="2" class="border-ligne w-full rounded-lg border px-3 py-2 text-sm" />
        </label>
      </div>

      <label class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{ t('finance.contributionForm.attachment') }}</span>
        <input
          type="file"
          required
          :accept="IMAGE_UPLOAD_ACCEPT"
          class="border-ligne w-full rounded-lg border px-3 py-2 text-sm"
          @change="onAttachmentChange"
        />
        <span v-if="attachment" class="text-texte-2 block text-xs">{{ attachment.name }}</span>
        <span v-if="attachmentError" class="text-critique block text-xs">{{ attachmentError }}</span>
      </label>

      <div class="flex justify-end gap-2">
        <Button variant="ghost" type="button" @click="emit('cancel')">{{ t('common.cancel') }}</Button>
        <Button variant="primary" type="submit" :loading="saving">
          {{ t('finance.contributionForm.submit') }}
        </Button>
      </div>
    </template>
  </form>
</template>
