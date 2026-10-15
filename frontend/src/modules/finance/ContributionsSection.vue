<script setup lang="ts">
// Capital contributions list with edit / cancel controls (2026-10-15).
// Edit: associate + date (needs an untouched apport and a reason) and
// reference / note. Cancel: admin only, contre-passation with a reason.
// The backend (ShareholderContributionService) enforces every rule; the
// buttons only mirror them (`blocked_reason` becomes the tooltip).
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import AppAlert from '@/components/ui/AppAlert.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Modal from '@/components/ui/Modal.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { formatMoney } from '@/utils/currency'
import { useAuthStore } from '@/stores/auth'
import {
  cancelShareholderContribution,
  shareholderContributionResource,
  updateShareholderContribution,
} from './api'
import type { Shareholder, ShareholderContribution } from './types'

const props = defineProps<{ shareholders: Shareholder[] }>()
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

const contributions = ref<ShareholderContribution[]>([])
const banks = ref<AccountOption[]>([])
const cashes = ref<AccountOption[]>([])
const loadError = ref('')

async function load() {
  loadError.value = ''
  try {
    const [list, b, c] = await Promise.all([
      shareholderContributionResource.list({}),
      bankAccountResource.list({}),
      cashAccountResource.list({}),
    ])
    contributions.value = [...list.results]
    banks.value = [...b.results]
    cashes.value = [...c.results]
  } catch {
    loadError.value = t('finance.shareholder.capitalList.loadError')
  }
}
onMounted(load)

function accountLabel(c: ShareholderContribution): string {
  if (c.bank_account) return banks.value.find((a) => a.id === c.bank_account)?.name ?? '—'
  if (c.cash_account) return cashes.value.find((a) => a.id === c.cash_account)?.name ?? '—'
  return '—'
}

function statusOf(c: ShareholderContribution): 'cancelled' | 'partial' | 'active' {
  if (c.is_cancelled) return 'cancelled'
  if (Number(c.amount_returned) > 0) return 'partial'
  return 'active'
}
const statusVariant = { cancelled: 'neutre', partial: 'ecart', active: 'livre' } as const

// --- Edit --------------------------------------------------------------------
const editing = ref<ShareholderContribution | null>(null)
const editForm = ref({ shareholder: '', date: '', reference: '', notes: '', reason: '' })
const busy = ref(false)
const dialogError = ref('')

const canMoveEditing = computed(() => editing.value != null && !editing.value.blocked_reason)
const sensitiveChanged = computed(
  () =>
    editing.value != null &&
    (Number(editForm.value.shareholder) !== editing.value.shareholder ||
      editForm.value.date !== editing.value.date),
)

function openEdit(c: ShareholderContribution) {
  editing.value = c
  editForm.value = {
    shareholder: String(c.shareholder),
    date: c.date,
    reference: c.reference,
    notes: c.notes,
    reason: '',
  }
  dialogError.value = ''
}

async function submitEdit() {
  const c = editing.value
  if (!c) return
  busy.value = true
  dialogError.value = ''
  try {
    await updateShareholderContribution(c.id, {
      ...(sensitiveChanged.value
        ? {
            shareholder: Number(editForm.value.shareholder),
            date: editForm.value.date,
            reason: editForm.value.reason,
          }
        : {}),
      reference: editForm.value.reference,
      notes: editForm.value.notes,
    })
    editing.value = null
    await load()
    emit('changed')
  } catch (e) {
    dialogError.value = errorText(e, t('finance.shareholder.capitalList.saveError'))
  } finally {
    busy.value = false
  }
}

// --- Cancel ------------------------------------------------------------------
const cancelling = ref<ShareholderContribution | null>(null)
const cancelReason = ref('')

function openCancel(c: ShareholderContribution) {
  cancelling.value = c
  cancelReason.value = ''
  dialogError.value = ''
}

async function submitCancel() {
  const c = cancelling.value
  if (!c) return
  busy.value = true
  dialogError.value = ''
  try {
    await cancelShareholderContribution(c.id, cancelReason.value.trim())
    cancelling.value = null
    await load()
    emit('changed')
  } catch (e) {
    dialogError.value = errorText(e, t('finance.shareholder.capitalList.cancelError'))
  } finally {
    busy.value = false
  }
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

const shareholderOptions = computed(() => props.shareholders)
defineExpose({ load })
</script>

<template>
  <Card :title="t('finance.shareholder.capitalList.title')" data-test="contributions-section">
    <p class="text-texte-2 mb-3 text-sm">{{ t('finance.shareholder.capitalList.help') }}</p>
    <AppAlert v-if="loadError" :message="loadError" />
    <div class="overflow-x-auto">
      <table class="w-full text-start text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">{{ t('finance.shareholder.capital.date') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('masterData.fields.name') }}</th>
            <th class="px-3 py-2.5 text-end font-medium">
              {{ t('finance.shareholder.capital.amount') }}
            </th>
            <th class="px-3 py-2.5 text-end font-medium">
              {{ t('finance.shareholder.capitalList.remaining') }}
            </th>
            <th class="px-3 py-2.5 font-medium">{{ t('finance.shareholder.capital.account') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('masterData.fields.active') }}</th>
            <th class="px-3 py-2.5"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="c in contributions"
            :key="c.id"
            :data-test="`contribution-row-${c.id}`"
            class="border-ligne border-b last:border-0"
            :class="c.is_cancelled ? 'text-texte-3 line-through' : ''"
          >
            <td class="px-3 py-2.5 whitespace-nowrap">{{ c.date }}</td>
            <td class="px-3 py-2.5">{{ c.shareholder_detail?.name ?? '—' }}</td>
            <td class="px-3 py-2.5 text-end"><MonoValue :value="formatMoney(c.amount)" /></td>
            <td class="px-3 py-2.5 text-end">
              <MonoValue :value="formatMoney(c.remaining_capital)" />
            </td>
            <td class="px-3 py-2.5">{{ accountLabel(c) }}</td>
            <td class="px-3 py-2.5 no-underline">
              <Badge :variant="statusVariant[statusOf(c)]">
                {{ t(`finance.shareholder.capitalList.status.${statusOf(c)}`) }}
              </Badge>
              <p
                v-if="c.is_cancelled && c.cancel_reason"
                class="text-texte-2 mt-1 text-xs no-underline"
              >
                {{ c.cancel_reason }}
              </p>
            </td>
            <td class="px-3 py-2.5 text-end whitespace-nowrap">
              <template v-if="!c.is_cancelled">
                <Button
                  variant="ghost"
                  :data-test="`edit-contribution-${c.id}`"
                  @click="openEdit(c)"
                  >{{ t('masterData.edit') }}</Button
                >
                <Button
                  v-if="isAdmin"
                  variant="ghost"
                  :data-test="`cancel-contribution-${c.id}`"
                  :disabled="!!c.blocked_reason"
                  :title="c.blocked_reason ?? ''"
                  @click="openCancel(c)"
                  >{{ t('finance.shareholder.capitalList.cancel') }}</Button
                >
              </template>
            </td>
          </tr>
          <tr v-if="contributions.length === 0">
            <td colspan="7" class="text-texte-3 px-3 py-6 text-center">
              {{ t('finance.shareholder.capital.empty') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Modal
      v-if="editing"
      :title="t('finance.shareholder.capitalList.editTitle')"
      @close="editing = null"
    >
      <form data-test="edit-contribution-dialog" class="space-y-4" @submit.prevent="submitEdit">
        <p class="text-texte-2 text-sm">
          {{ formatMoney(editing.amount) }} — {{ accountLabel(editing) }}
        </p>
        <p
          v-if="editing.blocked_reason"
          class="border-ligne bg-sable text-texte-2 rounded-lg border p-2.5 text-sm"
        >
          {{ editing.blocked_reason }}
        </p>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="edit_contribution_shareholder">{{
            t('finance.contributionForm.shareholder')
          }}</label>
          <select
            id="edit_contribution_shareholder"
            v-model="editForm.shareholder"
            :disabled="!canMoveEditing"
            class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2"
          >
            <option v-for="s in shareholderOptions" :key="s.id" :value="String(s.id)">
              {{ s.name }}
            </option>
          </select>
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="edit_contribution_date">{{
            t('finance.contributionForm.date')
          }}</label>
          <input
            id="edit_contribution_date"
            v-model="editForm.date"
            type="date"
            :disabled="!canMoveEditing"
            class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="edit_contribution_reference">{{
            t('finance.contributionForm.reference')
          }}</label>
          <input
            id="edit_contribution_reference"
            v-model="editForm.reference"
            class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="edit_contribution_notes">{{
            t('finance.contributionForm.note')
          }}</label>
          <textarea
            id="edit_contribution_notes"
            v-model="editForm.notes"
            class="border-ligne-forte min-h-16 w-full rounded-lg border bg-white px-3.5 py-2"
          />
        </div>
        <div v-if="sensitiveChanged" class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="edit_contribution_reason">{{
            t('finance.shareholder.capitalList.reason')
          }}</label>
          <textarea
            id="edit_contribution_reason"
            v-model="editForm.reason"
            data-test="edit-contribution-reason"
            required
            class="border-ligne-forte min-h-16 w-full rounded-lg border bg-white px-3.5 py-2"
          />
        </div>
        <p class="text-texte-3 text-xs">{{ t('finance.shareholder.capitalList.amountLocked') }}</p>
        <AppAlert v-if="dialogError" :message="dialogError" />
        <div class="flex justify-end gap-3">
          <Button variant="ghost" @click="editing = null">{{ t('common.cancel') }}</Button>
          <Button
            type="submit"
            variant="primary"
            data-test="save-contribution"
            :loading="busy"
            :disabled="sensitiveChanged && !editForm.reason.trim()"
            >{{ t('common.save') }}</Button
          >
        </div>
      </form>
    </Modal>

    <Modal
      v-if="cancelling"
      :title="t('finance.shareholder.capitalList.cancelTitle')"
      @close="cancelling = null"
    >
      <form data-test="cancel-contribution-dialog" class="space-y-4" @submit.prevent="submitCancel">
        <p class="font-semibold">
          {{ cancelling.shareholder_detail?.name }} — {{ formatMoney(cancelling.amount) }}
        </p>
        <p class="border-critique bg-critique-tint text-critique rounded-lg border p-2.5 text-sm">
          {{
            t('finance.shareholder.capitalList.cancelWarning', {
              amount: formatMoney(cancelling.amount),
              account: accountLabel(cancelling),
            })
          }}
        </p>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="cancel_contribution_reason">{{
            t('finance.shareholder.capitalList.reason')
          }}</label>
          <textarea
            id="cancel_contribution_reason"
            v-model="cancelReason"
            data-test="cancel-contribution-reason"
            required
            class="border-ligne-forte min-h-20 w-full rounded-lg border bg-white px-3.5 py-2"
          />
        </div>
        <AppAlert v-if="dialogError" :message="dialogError" />
        <div class="flex justify-end gap-3">
          <Button variant="ghost" @click="cancelling = null">{{ t('common.cancel') }}</Button>
          <Button
            type="submit"
            variant="danger"
            data-test="confirm-cancel-contribution"
            :loading="busy"
            :disabled="!cancelReason.trim()"
            >{{ t('finance.shareholder.capitalList.cancel') }}</Button
          >
        </div>
      </form>
    </Modal>
  </Card>
</template>
