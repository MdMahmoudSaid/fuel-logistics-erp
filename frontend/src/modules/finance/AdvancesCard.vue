<script setup lang="ts">
// "Avances" section shared by the customer, supplier and transporter ledgers
// (client request 2026-10-11: an advance must have its own section, not sit
// among the payments). Each ledger maps its own advance rows to AdvanceRow.
import { useI18n } from 'vue-i18n'
import Badge from '@/components/ui/Badge.vue'
import Card from '@/components/ui/Card.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { formatMoney } from '@/utils/currency'

export interface AdvanceRow {
  id: number
  date: string
  reference: string
  account: string | null
  amount: string
  remaining: string
  proofUrl: string | null
  reversed?: boolean
}

defineProps<{
  rows: AdvanceRow[]
  exportingId?: number | null
  cancellingId?: number | null
  canCancel?: boolean
}>()

const emit = defineEmits<{ pdf: [id: number]; preview: [url: string]; cancel: [id: number] }>()

const { t } = useI18n()

function status(row: AdvanceRow) {
  if (row.reversed) return { variant: 'critique' as const, label: t('finance.advances.cancelled') }
  if (Number(row.remaining) <= 0)
    return { variant: 'livre' as const, label: t('finance.advances.used') }
  if (Number(row.remaining) < Number(row.amount)) {
    return { variant: 'ecart' as const, label: t('finance.advances.partlyUsed') }
  }
  return { variant: 'transit' as const, label: t('finance.advances.open') }
}
</script>

<template>
  <Card :title="t('finance.advances.title')">
    <div class="overflow-x-auto">
      <table class="w-full text-start text-sm" data-test="advances-table">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-2 py-1.5 font-medium">{{ t('finance.advances.table.date') }}</th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.advances.table.reference') }}</th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.advances.table.account') }}</th>
            <th class="px-2 py-1.5 text-right font-medium">
              {{ t('finance.advances.table.amount') }}
            </th>
            <th class="px-2 py-1.5 text-right font-medium">
              {{ t('finance.advances.table.remaining') }}
            </th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.advances.table.status') }}</th>
            <th class="px-2 py-1.5 font-medium">{{ t('finance.advances.table.proof') }}</th>
            <th class="px-2 py-1.5 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.id"
            class="border-ligne border-b last:border-0"
            :class="row.reversed ? 'opacity-60' : ''"
          >
            <td class="px-2 py-1.5 whitespace-nowrap">{{ row.date }}</td>
            <td class="px-2 py-1.5">{{ row.reference || '—' }}</td>
            <td class="px-2 py-1.5">{{ row.account || '—' }}</td>
            <td class="text-texte px-2 py-1.5 text-right font-medium">
              <MonoValue
                :class="row.reversed ? 'text-texte-3 line-through' : ''"
                :value="formatMoney(row.amount)"
              />
            </td>
            <td class="px-2 py-1.5 text-right">
              <MonoValue :value="formatMoney(row.reversed ? 0 : row.remaining)" />
            </td>
            <td class="px-2 py-1.5">
              <Badge :variant="status(row).variant">{{ status(row).label }}</Badge>
            </td>
            <td class="px-2 py-1.5">
              <button
                v-if="row.proofUrl"
                type="button"
                class="text-bitume underline"
                @click="emit('preview', row.proofUrl)"
              >
                {{ t('finance.partyLedger.viewProof') }}
              </button>
              <span v-else class="text-texte-3">—</span>
            </td>
            <td class="px-2 py-1.5 text-right">
              <div class="flex justify-end gap-3">
                <button
                  type="button"
                  data-test="advance-pdf"
                  class="text-bitume underline disabled:opacity-50"
                  :disabled="exportingId === row.id"
                  @click="emit('pdf', row.id)"
                >
                  {{ t('finance.partyLedger.pdf') }}
                </button>
                <button
                  v-if="canCancel && !row.reversed"
                  type="button"
                  data-test="advance-cancel"
                  class="text-critique disabled:opacity-50"
                  :disabled="cancellingId === row.id"
                  @click="emit('cancel', row.id)"
                >
                  {{ t('finance.openingDebt.cancel') }}
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="rows.length === 0">
            <td colspan="8" class="text-texte-3 px-2 py-4 text-center">
              {{ t('finance.advances.none') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </Card>
</template>
