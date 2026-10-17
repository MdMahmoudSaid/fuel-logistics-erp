<script setup lang="ts">
// "Bénéfices ajoutés" (client request 2026-10-17): profit entered by hand,
// outside any trip. It counts in the net profit and is shared between the
// associates by the next period closure; with an account chosen the money
// also enters the treasury (backend ManualProfitService posts both
// together). Admin only - the backend enforces it, this only hides the
// buttons.
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import AppAlert from '@/components/ui/AppAlert.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Modal from '@/components/ui/Modal.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { useAuthStore } from '@/stores/auth'
import { formatMoney } from '@/utils/currency'
import { cancelManualProfit, createManualProfit, manualProfitResource } from './api'
import type { ManualProfit } from './types'

const emit = defineEmits<{ changed: [] }>()

const { t } = useI18n()
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role_detail?.name === 'Admin')

interface AccountOption {
  id: number
  name: string
}
const bankAccountResource = createResourceApi<AccountOption>('/bank-accounts/')
const cashAccountResource = createResourceApi<AccountOption>('/cash-accounts/')

const profits = ref<ManualProfit[]>([])
const banks = ref<AccountOption[]>([])
const cashes = ref<AccountOption[]>([])
const loadError = ref('')
const busy = ref(false)
const dialogError = ref('')

async function load() {
  loadError.value = ''
  try {
    const [list, b, c] = await Promise.all([
      manualProfitResource.list({}),
      bankAccountResource.list({}),
      cashAccountResource.list({}),
    ])
    profits.value = [...list.results]
    banks.value = [...b.results]
    cashes.value = [...c.results]
  } catch {
    loadError.value = t('finance.profit.added.loadError')
  }
}
onMounted(load)

function accountLabel(p: ManualProfit): string {
  if (p.bank_account) return banks.value.find((a) => a.id === p.bank_account)?.name ?? '—'
  if (p.cash_account) return cashes.value.find((a) => a.id === p.cash_account)?.name ?? '—'
  return '—'
}

function errorText(e: unknown, fallback: string): string {
  const data = (e as { response?: { data?: Record<string, unknown> } })?.response?.data
  if (!data) return fallback
  if (typeof data.detail === 'string') return data.detail
  const first = Object.values(data)[0]
  if (Array.isArray(first) && typeof first[0] === 'string') return first[0]
  if (typeof first === 'string') return first
  return fallback
}

// --- Add ---------------------------------------------------------------------
const adding = ref(false)
// 'none' = profit only, otherwise 'bank:<id>' / 'cash:<id>'.
const account = ref('none')
const form = ref({ amount: '', date: '', note: '' })

function openAdd() {
  form.value = { amount: '', date: new Date().toISOString().slice(0, 10), note: '' }
  // Default to the first bank account: the money normally lands in the treasury.
  account.value = banks.value[0] ? `bank:${banks.value[0].id}` : 'none'
  dialogError.value = ''
  adding.value = true
}

const canSubmit = computed(() => Number(form.value.amount) > 0 && form.value.note.trim() !== '')

async function submitAdd() {
  if (!canSubmit.value) {
    dialogError.value = t('finance.profit.added.positive')
    return
  }
  busy.value = true
  dialogError.value = ''
  const [kind, id] = account.value.split(':')
  try {
    await createManualProfit({
      amount: String(form.value.amount),
      date: form.value.date,
      note: form.value.note.trim(),
      bank_account: kind === 'bank' ? Number(id) : null,
      cash_account: kind === 'cash' ? Number(id) : null,
    })
    adding.value = false
    await load()
    emit('changed')
  } catch (e) {
    dialogError.value = errorText(e, t('finance.profit.added.saveError'))
  } finally {
    busy.value = false
  }
}

// --- Cancel ------------------------------------------------------------------
const cancelling = ref<ManualProfit | null>(null)
const cancelReason = ref('')

function openCancel(p: ManualProfit) {
  cancelling.value = p
  cancelReason.value = ''
  dialogError.value = ''
}

async function submitCancel() {
  const p = cancelling.value
  if (!p) return
  busy.value = true
  dialogError.value = ''
  try {
    await cancelManualProfit(p.id, cancelReason.value.trim())
    cancelling.value = null
    await load()
    emit('changed')
  } catch (e) {
    dialogError.value = errorText(e, t('finance.profit.added.cancelError'))
  } finally {
    busy.value = false
  }
}

defineExpose({ openAdd, load })
</script>

<template>
  <Card :title="t('finance.profit.added.title')" data-test="manual-profit-section">
    <div class="mb-3 flex flex-wrap items-start justify-between gap-3">
      <p class="text-texte-2 max-w-2xl text-sm">{{ t('finance.profit.added.help') }}</p>
      <Button v-if="isAdmin" variant="primary" data-test="add-manual-profit" @click="openAdd">
        {{ t('finance.profit.added.add') }}
      </Button>
    </div>
    <AppAlert v-if="loadError" :message="loadError" />
    <div class="overflow-x-auto">
      <table class="w-full text-start text-sm">
        <tbody>
          <tr
            v-for="p in profits"
            :key="p.id"
            :data-test="`manual-profit-row-${p.id}`"
            class="border-ligne border-b last:border-0"
            :class="p.is_cancelled ? 'text-texte-3 line-through' : ''"
          >
            <td class="px-3 py-2.5 whitespace-nowrap">{{ p.date }}</td>
            <td class="px-3 py-2.5 text-end"><MonoValue :value="formatMoney(p.amount)" /></td>
            <td class="px-3 py-2.5">
              {{ p.note }}
              <span v-if="p.is_cancelled && p.cancel_reason" class="block text-xs no-underline">
                {{ p.cancel_reason }}
              </span>
            </td>
            <td class="px-3 py-2.5">{{ accountLabel(p) }}</td>
            <td class="px-3 py-2.5 text-end whitespace-nowrap no-underline">
              <Badge v-if="p.is_cancelled" variant="neutre">{{
                t('finance.profit.added.cancelled')
              }}</Badge>
              <Button
                v-else-if="isAdmin"
                variant="ghost"
                :data-test="`cancel-manual-profit-${p.id}`"
                :disabled="!!p.blocked_reason"
                :title="p.blocked_reason ?? ''"
                @click="openCancel(p)"
                >{{ t('finance.profit.added.cancel') }}</Button
              >
            </td>
          </tr>
          <tr v-if="profits.length === 0">
            <td class="text-texte-3 px-3 py-6 text-center">
              {{ t('finance.profit.added.empty') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Modal v-if="adding" :title="t('finance.profit.added.addTitle')" @close="adding = false">
      <form data-test="add-manual-profit-dialog" class="space-y-4" @submit.prevent="submitAdd">
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="space-y-1.5">
            <span class="text-texte-2 text-sm font-medium">{{
              t('finance.profit.added.amount')
            }}</span>
            <input
              v-model="form.amount"
              data-test="manual-profit-amount"
              type="number"
              min="0.01"
              step="0.01"
              class="border-ligne-forte h-11 w-full rounded-lg border bg-white px-3.5"
            />
          </label>
          <label class="space-y-1.5">
            <span class="text-texte-2 text-sm font-medium">{{
              t('finance.profit.added.date')
            }}</span>
            <input
              v-model="form.date"
              type="date"
              class="border-ligne-forte h-11 w-full rounded-lg border bg-white px-3.5"
            />
          </label>
        </div>
        <label class="block space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{ t('finance.profit.added.note') }}</span>
          <textarea
            v-model="form.note"
            data-test="manual-profit-note"
            :placeholder="t('finance.profit.added.notePlaceholder')"
            class="border-ligne-forte min-h-16 w-full rounded-lg border bg-white px-3.5 py-2"
          />
        </label>
        <label class="block space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.profit.added.account')
          }}</span>
          <select
            v-model="account"
            data-test="manual-profit-account"
            class="border-ligne-forte h-11 w-full rounded-lg border bg-white px-3.5"
          >
            <optgroup v-if="banks.length" :label="t('finance.profit.added.bank')">
              <option v-for="b in banks" :key="`b${b.id}`" :value="`bank:${b.id}`">
                {{ b.name }}
              </option>
            </optgroup>
            <optgroup v-if="cashes.length" :label="t('finance.profit.added.cash')">
              <option v-for="c in cashes" :key="`c${c.id}`" :value="`cash:${c.id}`">
                {{ c.name }}
              </option>
            </optgroup>
            <option value="none">{{ t('finance.profit.added.noAccount') }}</option>
          </select>
          <span class="text-texte-3 block text-xs">{{
            t('finance.profit.added.accountHelp')
          }}</span>
        </label>
        <AppAlert v-if="dialogError" :message="dialogError" />
        <div class="flex justify-end gap-3">
          <Button variant="ghost" type="button" @click="adding = false">{{
            t('common.cancel')
          }}</Button>
          <Button
            type="submit"
            variant="primary"
            data-test="save-manual-profit"
            :loading="busy"
            :disabled="!canSubmit"
            >{{ t('finance.profit.added.submit') }}</Button
          >
        </div>
      </form>
    </Modal>

    <Modal
      v-if="cancelling"
      :title="t('finance.profit.added.cancelTitle')"
      @close="cancelling = null"
    >
      <form
        data-test="cancel-manual-profit-dialog"
        class="space-y-4"
        @submit.prevent="submitCancel"
      >
        <p class="border-critique bg-critique-tint text-critique rounded-lg border p-2.5 text-sm">
          {{ t('finance.profit.added.cancelWarning', { amount: formatMoney(cancelling.amount) }) }}
        </p>
        <label class="block space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">{{
            t('finance.profit.added.reason')
          }}</span>
          <textarea
            v-model="cancelReason"
            data-test="cancel-manual-profit-reason"
            required
            class="border-ligne-forte min-h-20 w-full rounded-lg border bg-white px-3.5 py-2"
          />
        </label>
        <AppAlert v-if="dialogError" :message="dialogError" />
        <div class="flex justify-end gap-3">
          <Button variant="ghost" type="button" @click="cancelling = null">{{
            t('common.cancel')
          }}</Button>
          <Button
            type="submit"
            variant="danger"
            data-test="confirm-cancel-manual-profit"
            :loading="busy"
            :disabled="!cancelReason.trim()"
            >{{ t('finance.profit.added.cancel') }}</Button
          >
        </div>
      </form>
    </Modal>
  </Card>
</template>
