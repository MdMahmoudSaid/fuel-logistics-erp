<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { createSupplierAdvance, createTransporterAdvance, fetchPartyBalances } from './api'
import type { PartyBalance, PartyType } from './types'
import { formatMoney } from '@/utils/currency'
import { IMAGE_UPLOAD_ACCEPT, isAllowedImageFile } from '@/utils/imageUpload'

const emit = defineEmits<{
  success: []
  cancel: []
}>()

const props = withDefaults(
  defineProps<{
    initialPartyType?: PartyType
    initialPartyId?: number | null
    lockPartyType?: boolean
    lockParty?: boolean
  }>(),
  {
    initialPartyType: 'supplier',
    initialPartyId: null,
    lockPartyType: false,
    lockParty: false,
  },
)

const { t } = useI18n()

interface AccountOption {
  id: number
  name: string
  current_balance: string
}

const PARTY_TYPES: { value: PartyType; labelKey: string }[] = [
  { value: 'supplier', labelKey: 'finance.debtPayment.types.supplier' },
  { value: 'transporter', labelKey: 'finance.debtPayment.types.transporter' },
]

const bankAccountResource = createResourceApi<AccountOption>('/bank-accounts/')
const cashAccountResource = createResourceApi<AccountOption>('/cash-accounts/')

const partyType = ref<PartyType>(props.initialPartyType)
const partyId = ref('')
const accountKind = ref<'bank' | 'cash'>('bank')
const bankAccountId = ref('')
const cashAccountId = ref('')
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
    attachmentError.value = t('finance.advanceForm.imageOnlyError')
    return
  }
  attachment.value = file
  attachmentError.value = ''
}

const parties = ref<PartyBalance[]>([])
const banks = ref<AccountOption[]>([])
const cashAccounts = ref<AccountOption[]>([])
const loading = ref(true)
const partyLoading = ref(false)
const saving = ref(false)
const error = ref('')
const emptyPartyMessage = ref('')

const selectedParty = computed(
  () => parties.value.find((party) => party.id === Number(partyId.value)) ?? null,
)
const selectedAccount = computed(() =>
  accountKind.value === 'bank'
    ? (banks.value.find((bank) => bank.id === Number(bankAccountId.value)) ?? null)
    : (cashAccounts.value.find((account) => account.id === Number(cashAccountId.value)) ?? null),
)
const amountNumber = computed(() => Number(amount.value || 0))

// Single source of truth: net_balance is read exactly as returned by
// fetchPartyBalances() (backed by ControlledDebtPaymentService.
// describe_supplier_balance/describe_transporter_balance server-side) -
// this component never recomputes or second-guesses it.
async function loadParties() {
  partyLoading.value = true
  error.value = ''
  emptyPartyMessage.value = ''
  partyId.value = ''
  try {
    const fetched = await fetchPartyBalances(partyType.value)
    if (props.lockParty) {
      // Locked to a specific entity (e.g. opened from a supplier/transporter's
      // own ledger page): never let a missing match silently fall back to
      // another entity, and never expose other entities in the list.
      const lockedParty = fetched.find((party) => party.id === props.initialPartyId)
      parties.value = lockedParty ? [lockedParty] : []
      partyId.value = lockedParty ? String(lockedParty.id) : ''
      if (!lockedParty) {
        error.value = t('finance.advanceForm.errors.partyNotFound')
      }
    } else {
      const eligible = fetched.filter((party) => Number(party.net_balance) >= 0)
      parties.value = eligible
      const initialParty = eligible.find((party) => party.id === props.initialPartyId)
      partyId.value = initialParty
        ? String(initialParty.id)
        : eligible[0]
          ? String(eligible[0].id)
          : ''
      if (!eligible.length) {
        emptyPartyMessage.value = t('finance.advanceForm.errors.noEligibleParty')
      }
    }
  } catch {
    parties.value = []
    partyId.value = ''
    error.value = t('finance.advanceForm.loadError')
  } finally {
    partyLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [bankData, cashData] = await Promise.all([
      bankAccountResource.list(),
      cashAccountResource.list(),
      loadParties(),
    ])
    banks.value = bankData.results
    cashAccounts.value = cashData.results
    bankAccountId.value = banks.value[0]?.id ? String(banks.value[0].id) : ''
    cashAccountId.value = cashAccounts.value[0]?.id ? String(cashAccounts.value[0].id) : ''
  } catch {
    error.value = t('finance.advanceForm.loadError')
  } finally {
    loading.value = false
  }
}

function validate(): boolean {
  error.value = ''
  if (!selectedParty.value) {
    error.value = t('finance.advanceForm.errors.partyRequired')
    return false
  }
  if (!selectedAccount.value) {
    error.value = t('finance.advanceForm.errors.accountRequired')
    return false
  }
  if (amountNumber.value <= 0) {
    error.value = t('finance.advanceForm.errors.positiveAmount')
    return false
  }
  if (amountNumber.value > Number(selectedAccount.value.current_balance)) {
    error.value = t('finance.advanceForm.errors.insufficientBalance')
    return false
  }
  if (!attachment.value) {
    error.value = t('finance.advanceForm.errors.proofRequired')
    return false
  }
  return true
}

async function submit() {
  if (!validate() || !selectedParty.value || !selectedAccount.value || !attachment.value) return
  saving.value = true
  try {
    const payload = {
      bank_account: accountKind.value === 'bank' ? Number(bankAccountId.value) : null,
      cash_account: accountKind.value === 'cash' ? Number(cashAccountId.value) : null,
      // Backend DecimalFields are serialized/expected as strings; the
      // <input type="number"> element auto-casts through Vue's vModelText
      // directive even without a `.number` modifier, so amount.value can
      // be a runtime number despite its `ref<string>` type - always coerce
      // back to a string here.
      amount: String(amount.value),
      date: date.value,
      reference: reference.value,
      notes: note.value,
      attachment: attachment.value,
    }
    if (partyType.value === 'supplier') {
      await createSupplierAdvance({ supplier: selectedParty.value.id, ...payload })
    } else {
      await createTransporterAdvance({ transporter: selectedParty.value.id, ...payload })
    }
    emit('success')
  } catch (err: unknown) {
    const data = (err as { response?: { data?: Record<string, unknown> } }).response?.data
    const detail =
      (data?.detail as string | undefined) ??
      (Array.isArray(data?.non_field_errors) ? (data!.non_field_errors as string[])[0] : undefined)
    error.value = detail ?? t('finance.advanceForm.saveError')
  } finally {
    saving.value = false
  }
}

watch(partyType, loadParties)
onMounted(load)
</script>

<template>
  <form class="space-y-5" @submit.prevent="submit">
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else>
      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.type') }}</span>
          <select
            v-model="partyType"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
            :disabled="lockPartyType"
          >
            <option v-for="type in PARTY_TYPES" :key="type.value" :value="type.value">
              {{ t(type.labelKey) }}
            </option>
          </select>
        </label>

        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.party') }}</span>
          <select
            id="party"
            v-model="partyId"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
            :disabled="partyLoading || parties.length === 0 || lockParty"
          >
            <option v-for="party in parties" :key="party.id" :value="String(party.id)">
              {{ party.label }}
            </option>
          </select>
          <span v-if="emptyPartyMessage" class="text-texte-3 block text-xs">
            {{ emptyPartyMessage }}
          </span>
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-3">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.advanceForm.accountKind')
          }}</span>
          <select
            v-model="accountKind"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          >
            <option value="bank">{{ t('finance.advanceForm.bank') }}</option>
            <option value="cash">{{ t('finance.advanceForm.cash') }}</option>
          </select>
        </label>
        <label v-if="accountKind === 'bank'" class="space-y-1.5 sm:col-span-2">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.bank') }}</span>
          <select
            v-model="bankAccountId"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          >
            <option v-for="bank in banks" :key="bank.id" :value="String(bank.id)">
              {{ bank.name }}
            </option>
          </select>
        </label>
        <label v-else class="space-y-1.5 sm:col-span-2">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.cash') }}</span>
          <select
            v-model="cashAccountId"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          >
            <option v-for="account in cashAccounts" :key="account.id" :value="String(account.id)">
              {{ account.name }}
            </option>
          </select>
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.advanceForm.amount')
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
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.date') }}</span>
          <input
            v-model="date"
            type="date"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          />
        </label>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.advanceForm.reference')
          }}</span>
          <input
            v-model="reference"
            class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
          />
        </label>
        <label class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.note') }}</span>
          <textarea
            v-model="note"
            rows="2"
            class="border-ligne w-full rounded-lg border px-3 py-2 text-sm"
          />
        </label>
      </div>

      <label class="block space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{
          t('finance.advanceForm.attachment')
        }}</span>
        <input
          type="file"
          required
          :accept="IMAGE_UPLOAD_ACCEPT"
          class="border-ligne w-full rounded-lg border px-3 py-2 text-sm"
          @change="onAttachmentChange"
        />
        <span v-if="attachment" class="text-texte-2 block text-xs">{{ attachment.name }}</span>
        <span v-if="attachmentError" class="text-critique block text-xs">{{
          attachmentError
        }}</span>
      </label>

      <div v-if="selectedAccount" class="border-ligne rounded-lg border bg-sable p-3 text-sm">
        <p class="text-texte-3 text-xs font-medium uppercase">
          {{ t('finance.advanceForm.availableBalance') }}
        </p>
        <MonoValue :value="formatMoney(selectedAccount.current_balance)" align="left" />
      </div>

      <div class="flex justify-end gap-2">
        <Button variant="ghost" type="button" @click="emit('cancel')">{{
          t('common.cancel')
        }}</Button>
        <Button variant="primary" type="submit" :loading="saving">
          {{ t('finance.advanceForm.submit') }}
        </Button>
      </div>
    </template>
  </form>
</template>
