<script setup lang="ts">
// "Dettes antérieures" section shared by the customer, supplier and
// transporter ledgers (2026-10-11). Hidden while the party has none.
import AppAlert from '@/components/ui/AppAlert.vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { confirmDialog } from '@/composables/useConfirmDialog'
import Badge from '@/components/ui/Badge.vue'
import Card from '@/components/ui/Card.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { formatMoney } from '@/utils/currency'
import { cancelOpeningDebt } from './api'
import type { OpeningDebt } from './types'

const props = defineProps<{ debts: OpeningDebt[] }>()
const emit = defineEmits<{ changed: []; preview: [url: string] }>()

const { t } = useI18n()
// Read lazily: the store is only needed once there is a debt row to show.
const canCancel = computed(() => useAuthStore().can('finance', 'cancel'))
const cancellingId = ref<number | null>(null)
const error = ref('')

function badgeVariant(status: OpeningDebt['status']) {
  if (status === 'PAID') return 'livre' as const
  if (status === 'PARTIALLY_PAID') return 'ecart' as const
  if (status === 'CANCELLED') return 'critique' as const
  return 'neutre' as const
}

async function onCancel(debt: OpeningDebt) {
  if (!(await confirmDialog(t('finance.openingDebt.cancelConfirm')))) return
  cancellingId.value = debt.id
  error.value = ''
  try {
    await cancelOpeningDebt(debt.id)
    emit('changed')
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail || t('finance.openingDebt.cancelError')
  } finally {
    cancellingId.value = null
  }
}
</script>

<template>
  <Card v-if="props.debts.length" :title="t('finance.openingDebt.section')">
    <AppAlert v-if="error" :message="error" />
    <div class="overflow-x-auto">
      <table class="w-full text-start text-sm" data-test="opening-debts-table">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-2 py-1.5 font-medium">{{ t('finance.openingDebt.table.date') }}</th>
            <th class="px-2 py-1.5 font-medium">
              {{ t('finance.openingDebt.table.reference') }}
            </th>
            <th class="px-2 py-1.5 text-right font-medium">
              {{ t('finance.openingDebt.table.amount') }}
            </th>
            <th class="px-2 py-1.5 text-right font-medium">
              {{ t('finance.openingDebt.table.paid') }}
            </th>
            <th class="px-2 py-1.5 text-right font-medium">
              {{ t('finance.openingDebt.table.remaining') }}
            </th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.openingDebt.table.status') }}</th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.openingDebt.table.proof') }}</th>
            <th class="px-2 py-1.5 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="debt in props.debts"
            :key="debt.id"
            class="border-ligne border-b last:border-0"
          >
            <td class="px-2 py-1.5 whitespace-nowrap">{{ debt.date }}</td>
            <td class="px-2 py-1.5">
              <span>{{ debt.reference || '—' }}</span>
              <span v-if="debt.notes" class="text-texte-3 block text-xs">{{ debt.notes }}</span>
            </td>
            <td class="px-2 py-1.5 text-right">
              <MonoValue :value="formatMoney(debt.amount)" />
            </td>
            <td class="px-2 py-1.5 text-right">
              <MonoValue :value="formatMoney(debt.paid_amount)" />
            </td>
            <td class="text-texte px-2 py-1.5 text-right font-medium">
              <MonoValue :value="formatMoney(debt.remaining_amount)" />
            </td>
            <td class="px-2 py-1.5">
              <Badge :variant="badgeVariant(debt.status)">
                {{ t(`finance.openingDebt.status.${debt.status}`) }}
              </Badge>
            </td>
            <td class="px-2 py-1.5">
              <button
                v-if="debt.proof_url"
                type="button"
                class="text-bitume underline"
                @click="emit('preview', debt.proof_url)"
              >
                {{ t('finance.partyLedger.viewProof') }}
              </button>
              <span v-else class="text-texte-3">—</span>
            </td>
            <td class="px-2 py-1.5 text-right">
              <button
                v-if="canCancel"
                type="button"
                data-test="opening-debt-cancel"
                class="text-critique disabled:opacity-50"
                :disabled="cancellingId === debt.id"
                @click="onCancel(debt)"
              >
                {{ t('finance.openingDebt.cancel') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </Card>
</template>
