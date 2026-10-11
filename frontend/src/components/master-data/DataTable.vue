<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { FieldOption, FieldType } from './types'
import { formatPhoneDisplay } from '@/data/countries'
import { formatMoney, formatQuantity } from '@/utils/currency'
import MonoValue from '@/components/ui/MonoValue.vue'

defineProps<{
  columns: {
    key: string
    label: string
    type?: FieldType
    options?: FieldOption[]
    trueLabel?: string
    falseLabel?: string
  }[]
  rows: Record<string, unknown>[]
  activeToggle?: boolean
  ledgerRouteName?: string
}>()

// UI recette fix (2026-09-05): money/quantity columns previously printed
// plain text (no font-mono/tabular-nums, no right alignment), the same
// "digits don't line up between rows" alignment bug the rest of the app
// avoids by always going through MonoValue (see that component's own
// docstring) - this only changes how these two column types render, never
// the underlying data.
function isNumericColumn(type?: FieldType): boolean {
  return type === 'money' || type === 'quantity'
}

defineEmits<{
  edit: [row: Record<string, unknown>]
  delete: [row: Record<string, unknown>]
  'toggle-active': [row: Record<string, unknown>]
}>()

const { t } = useI18n()

type Column = {
  key: string
  type?: FieldType
  options?: FieldOption[]
  trueLabel?: string
  falseLabel?: string
}

// Texte affiché pour une cellule - partagé par le tableau (écran large) et
// les cartes (téléphone).
function cellText(col: Column, row: Record<string, unknown>): string {
  const value = row[col.key]
  if (col.type === 'checkbox')
    return value
      ? (col.trueLabel ?? t('masterData.statusActive'))
      : (col.falseLabel ?? t('masterData.statusInactive'))
  if (col.type === 'select' && col.options)
    return col.options.find((o) => o.value === String(value))?.label ?? String(value ?? '')
  if (col.type === 'phone') return formatPhoneDisplay(value as string)
  if (col.type === 'money') return formatMoney((value as string | number | undefined) ?? 0)
  if (col.type === 'quantity') return formatQuantity((value as string | number | undefined) ?? 0)
  return value === null || value === undefined ? '' : String(value)
}

const cardAction = 'border-ligne-forte h-10 rounded-lg border bg-white px-3 text-sm'
</script>

<template>
  <div>
    <!-- Téléphone : une carte par enregistrement, actions en boutons tactiles. -->
    <ul class="divide-ligne divide-y md:hidden">
      <li v-for="row in rows" :key="`card-${String(row.id)}`" class="p-4">
        <p class="text-texte font-semibold break-words">
          {{ columns.length ? cellText(columns[0]!, row) : '' }}
        </p>
        <dl class="mt-2 space-y-1.5 text-sm">
          <div
            v-for="col in columns.slice(1)"
            :key="col.key"
            class="flex items-baseline justify-between gap-3"
          >
            <dt class="text-texte-3 shrink-0">{{ col.label }}</dt>
            <dd class="text-texte min-w-0 text-end break-words">
              <MonoValue v-if="isNumericColumn(col.type)" :value="cellText(col, row)" />
              <template v-else>{{ cellText(col, row) || '—' }}</template>
            </dd>
          </div>
        </dl>
        <div class="mt-3 flex flex-wrap gap-2">
          <RouterLink
            v-if="ledgerRouteName"
            :class="[cardAction, 'text-texte inline-flex items-center']"
            :to="{ name: ledgerRouteName, params: { id: String(row.id) } }"
          >
            {{ t('masterData.viewLedger') }}
          </RouterLink>
          <button type="button" :class="[cardAction, 'text-texte']" @click="$emit('edit', row)">
            {{ t('masterData.edit') }}
          </button>
          <button
            v-if="activeToggle"
            type="button"
            :class="[cardAction, row.is_active ? 'text-critique' : 'text-livre']"
            @click="$emit('toggle-active', row)"
          >
            {{ row.is_active ? t('masterData.deactivate') : t('masterData.activate') }}
          </button>
          <button
            v-else
            type="button"
            :class="[cardAction, 'text-critique']"
            @click="$emit('delete', row)"
          >
            {{ t('common.delete') }}
          </button>
        </div>
      </li>
      <li v-if="rows.length === 0" class="text-texte-3 px-3 py-8 text-center text-sm">
        {{ t('masterData.noRecords') }}
      </li>
    </ul>

    <table class="hidden w-full min-w-max text-start text-sm md:table">
      <thead>
        <tr class="border-ligne text-texte-2 border-b">
          <th
            v-for="col in columns"
            :key="col.key"
            class="px-3 py-2.5 font-medium whitespace-nowrap align-middle"
            :class="isNumericColumn(col.type) ? 'text-end' : 'text-start'"
          >
            {{ col.label }}
          </th>
          <th class="px-3 py-2.5 align-middle" />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="String(row.id)"
          class="border-ligne hover:bg-sable border-b last:border-0"
        >
          <td
            v-for="col in columns"
            :key="col.key"
            class="px-3 py-2.5 align-middle whitespace-nowrap"
            :class="isNumericColumn(col.type) ? 'text-end' : 'text-start'"
          >
            <MonoValue v-if="isNumericColumn(col.type)" :value="cellText(col, row)" />
            <template v-else>{{ cellText(col, row) }}</template>
          </td>
          <td class="px-3 py-2.5 text-end align-middle whitespace-nowrap">
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
              <button
                v-else
                class="text-critique hover:brightness-90"
                @click="$emit('delete', row)"
              >
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
  </div>
</template>
