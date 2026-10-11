<script setup lang="ts">
// Editable lines of a commercial document: one input per column, add /
// remove a line, optional total of one numeric column.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatQuantity } from '@/utils/currency'

export interface LineColumn {
  field: string
  labelKey: string
  type?: 'text' | 'number'
  step?: string
}

const props = defineProps<{
  columns: LineColumn[]
  modelValue: Record<string, unknown>[]
  newLine: () => Record<string, unknown>
  totalField?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [lines: Record<string, unknown>[]] }>()
const { t } = useI18n()

const total = computed(() =>
  props.totalField
    ? props.modelValue.reduce((sum, line) => sum + (Number(line[props.totalField!]) || 0), 0)
    : 0,
)

function update(index: number, field: string, value: string) {
  emit(
    'update:modelValue',
    props.modelValue.map((line, i) => (i === index ? { ...line, [field]: value } : line)),
  )
}

const add = () => emit('update:modelValue', [...props.modelValue, props.newLine()])
const remove = (index: number) =>
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )

const inputClass =
  'border-ligne-forte h-10 w-full min-w-24 rounded-md border bg-white px-2 text-sm focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2'
</script>

<template>
  <div class="space-y-2">
    <div class="border-ligne overflow-x-auto rounded-lg border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-2 py-2 font-medium">#</th>
            <th v-for="column in columns" :key="column.field" class="px-2 py-2 font-medium">
              {{ t(column.labelKey) }}
            </th>
            <th class="px-2 py-2"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(line, index) in modelValue"
            :key="index"
            class="border-ligne border-b last:border-0"
            data-test="doc-line"
          >
            <td class="text-texte-3 px-2 py-1.5">{{ index + 1 }}</td>
            <td v-for="column in columns" :key="column.field" class="px-2 py-1.5">
              <input
                :value="line[column.field] ?? ''"
                :type="column.type === 'number' ? 'number' : 'text'"
                :step="column.step ?? (column.type === 'number' ? '0.01' : undefined)"
                :data-test="`line-${index}-${column.field}`"
                :class="inputClass"
                @input="update(index, column.field, ($event.target as HTMLInputElement).value)"
              />
            </td>
            <td class="px-2 py-1.5 text-right">
              <button
                type="button"
                class="text-sm text-red-700 underline"
                :aria-label="t('documents.common.removeLine')"
                @click="remove(index)"
              >
                ✕
              </button>
            </td>
          </tr>
          <tr v-if="!modelValue.length">
            <td :colspan="columns.length + 2" class="text-texte-3 px-2 py-4 text-center">
              {{ t('documents.common.noLines') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="flex items-center justify-between">
      <button type="button" data-test="add-line" class="text-bitume text-sm underline" @click="add">
        {{ t('documents.common.addLine') }}
      </button>
      <p v-if="totalField" class="text-sm font-semibold" data-test="lines-total">
        {{ t('documents.common.total') }} : {{ formatQuantity(total) }}
      </p>
    </div>
  </div>
</template>
