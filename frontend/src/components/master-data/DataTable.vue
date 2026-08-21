<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { FieldType } from './types'

defineProps<{
  columns: { key: string; label: string; type?: FieldType }[]
  rows: Record<string, unknown>[]
}>()

defineEmits<{ edit: [row: Record<string, unknown>]; delete: [row: Record<string, unknown>] }>()

const { t } = useI18n()
</script>

<template>
  <table class="w-full text-start text-sm">
    <thead>
      <tr class="border-ligne text-texte-2 border-b">
        <th v-for="col in columns" :key="col.key" class="px-3 py-2.5 font-medium">
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
        <td v-for="col in columns" :key="col.key" class="px-3 py-2.5">
          <template v-if="col.type === 'checkbox'">
            {{ row[col.key] ? t('masterData.statusActive') : t('masterData.statusInactive') }}
          </template>
          <template v-else>{{ row[col.key] }}</template>
        </td>
        <td class="px-3 py-2.5 text-end whitespace-nowrap">
          <span class="inline-flex items-center gap-3">
            <button class="text-texte-2 hover:text-texte" @click="$emit('edit', row)">
              {{ t('masterData.edit') }}
            </button>
            <button class="text-critique hover:brightness-90" @click="$emit('delete', row)">
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
