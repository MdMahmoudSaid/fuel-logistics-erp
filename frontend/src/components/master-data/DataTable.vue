<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { FieldOption, FieldType } from './types'
import { formatPhoneDisplay } from '@/data/countries'
import { formatMoney, formatQuantity } from '@/utils/currency'

defineProps<{
  columns: { key: string; label: string; type?: FieldType; options?: FieldOption[] }[]
  rows: Record<string, unknown>[]
  activeToggle?: boolean
  ledgerRouteName?: string
}>()

defineEmits<{
  edit: [row: Record<string, unknown>]
  delete: [row: Record<string, unknown>]
  'toggle-active': [row: Record<string, unknown>]
}>()

const { t } = useI18n()
</script>

<template>
  <table class="w-full min-w-max text-start text-sm">
    <thead>
      <tr class="border-ligne text-texte-2 border-b">
        <th
          v-for="col in columns"
          :key="col.key"
          class="px-3 py-2.5 font-medium whitespace-nowrap"
        >
          {{ col.label }}
        </th>
        <th class="px-3 py-2.5" />
      </tr>
    </thead>
    <tbody>
      <tr
        v-for="row in rows"
        :key="String(row.id)"
        class="border-ligne hover:bg-sable border-b last:border-0"
      >
        <td v-for="col in columns" :key="col.key" class="px-3 py-2.5 whitespace-nowrap">
          <template v-if="col.type === 'checkbox'">
            {{ row[col.key] ? t('masterData.statusActive') : t('masterData.statusInactive') }}
          </template>
          <template v-else-if="col.type === 'select' && col.options">
            {{ col.options.find((o) => o.value === String(row[col.key]))?.label ?? row[col.key] }}
          </template>
          <template v-else-if="col.type === 'phone'">
            {{ formatPhoneDisplay(row[col.key] as string) }}
          </template>
          <template v-else-if="col.type === 'money'">
            {{ formatMoney((row[col.key] as string | number | undefined) ?? 0) }}
          </template>
          <template v-else-if="col.type === 'quantity'">
            {{ formatQuantity((row[col.key] as string | number | undefined) ?? 0) }}
          </template>
          <template v-else>{{ row[col.key] }}</template>
        </td>
        <td class="px-3 py-2.5 text-end whitespace-nowrap">
          <span class="inline-flex items-center gap-3">
            <RouterLink
              v-if="ledgerRouteName"
              class="text-texte-2 hover:text-texte"
              :to="{ name: ledgerRouteName, params: { id: String(row.id) } }"
            >
              {{ t('masterData.viewLedger') }}
            </RouterLink>
            <button class="text-texte-2 hover:text-texte" @click="$emit('edit', row)">
              {{ t('masterData.edit') }}
            </button>
            <button
              v-if="activeToggle"
              class="hover:brightness-90"
              :class="row.is_active ? 'text-critique' : 'text-livre'"
              @click="$emit('toggle-active', row)"
            >
              {{ row.is_active ? t('masterData.deactivate') : t('masterData.activate') }}
            </button>
            <button v-else class="text-critique hover:brightness-90" @click="$emit('delete', row)">
              {{ t('common.delete') }}
            </button>
          </span>
        </td>
      </tr>
      <tr v-if="rows.length === 0">
        <td :colspan="columns.length + 1" class="text-texte-3 px-3 py-8 text-center">
          {{ t('masterData.noRecords') }}
        </td>
      </tr>
    </tbody>
  </table>
</template>
