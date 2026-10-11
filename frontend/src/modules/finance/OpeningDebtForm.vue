<script setup lang="ts">
// "Nouvelle dette" (client request 2026-10-11): a debt from before the app,
// recorded on a customer, supplier or transporter ledger. It never moves
// treasury (no account to pick): it only adds to the party's balance and is
// then settled by the ordinary payment flows.
import AppAlert from '@/components/ui/AppAlert.vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from '@/components/ui/Button.vue'
import FormActions from '@/components/ui/FormActions.vue'
import { createOpeningDebt } from './api'
import type { OpeningDebtPartyType } from './types'
import { IMAGE_UPLOAD_ACCEPT, isAllowedImageFile } from '@/utils/imageUpload'

const props = defineProps<{
  partyType: OpeningDebtPartyType
  partyId: number
  partyName: string
}>()

const emit = defineEmits<{
  success: []
  cancel: []
}>()

const { t } = useI18n()

const amount = ref('')
const date = ref(new Date().toISOString().slice(0, 10))
const reference = ref('')
const note = ref('')
const attachment = ref<File | null>(null)
const attachmentError = ref('')
const saving = ref(false)
const error = ref('')

const explanation = computed(() => t(`finance.openingDebt.explanation.${props.partyType}`))

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

async function submit() {
  error.value = ''
  if (Number(amount.value || 0) <= 0) {
    error.value = t('finance.openingDebt.errors.positiveAmount')
    return
  }
  if (!date.value) {
    error.value = t('finance.openingDebt.errors.dateRequired')
    return
  }
  if (attachmentError.value) return
  saving.value = true
  try {
    await createOpeningDebt({
      party_type: props.partyType,
      party_id: props.partyId,
      // <input type="number"> can hand back a number despite the ref type.
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
    error.value = detail ?? t('finance.openingDebt.saveError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="space-y-3" data-test="opening-debt-form" @submit.prevent="submit">
    <AppAlert v-if="error" :message="error" />

    <p class="border-ligne bg-sable text-texte-2 rounded-lg border p-3 text-sm">
      {{ explanation }}
    </p>

    <div class="grid gap-x-4 gap-y-3 sm:grid-cols-3">
      <label class="space-y-1">
        <span class="text-texte-2 text-sm font-medium">{{ t('finance.openingDebt.party') }}</span>
        <input
          :value="partyName"
          disabled
          class="border-ligne bg-sable h-11 w-full rounded-lg border px-3 text-sm"
        />
      </label>

      <label class="space-y-1">
        <span class="text-texte-2 text-sm font-medium">{{ t('finance.openingDebt.amount') }}</span>
        <input
          v-model="amount"
          data-test="opening-debt-amount"
          min="0.01"
          step="0.01"
          type="number"
          class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
        />
      </label>

      <label class="space-y-1">
        <span class="text-texte-2 text-sm font-medium">{{ t('finance.openingDebt.date') }}</span>
        <input
          v-model="date"
          type="date"
          class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
        />
      </label>

      <label class="space-y-1">
        <span class="text-texte-2 text-sm font-medium">{{
          t('finance.openingDebt.reference')
        }}</span>
        <input
          v-model="reference"
          class="border-ligne h-11 w-full rounded-lg border px-3 text-sm"
        />
      </label>

      <label class="space-y-1 sm:col-span-2">
        <span class="text-texte-2 text-sm font-medium">{{
          t('finance.advanceForm.attachment')
        }}</span>
        <input
          type="file"
          :accept="IMAGE_UPLOAD_ACCEPT"
          class="border-ligne w-full rounded-lg border px-3 py-2 text-sm"
          @change="onAttachmentChange"
        />
      </label>

      <label class="space-y-1 sm:col-span-3">
        <span class="text-texte-2 text-sm font-medium">{{ t('finance.advanceForm.note') }}</span>
        <textarea
          v-model="note"
          rows="1"
          class="border-ligne block min-h-11 w-full resize-y rounded-lg border px-3 py-2 text-sm"
        />
      </label>
    </div>
    <AppAlert v-if="attachmentError" :message="attachmentError" />

    <FormActions>
      <Button variant="ghost" type="button" @click="emit('cancel')">{{
        t('common.cancel')
      }}</Button>
      <Button variant="primary" type="submit" :loading="saving" data-test="opening-debt-submit">
        {{ t('finance.openingDebt.submit') }}
      </Button>
    </FormActions>
  </form>
</template>
