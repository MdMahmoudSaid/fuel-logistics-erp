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

// Grille des colonnes sur écran large ; sur téléphone chaque ligne devient
// une carte avec ses champs étiquetés sur deux colonnes.
const gridColumns = computed(() => `2rem repeat(${props.columns.length}, minmax(6rem, 1fr)) 2.5rem`)

const inputClass =
  'border-ligne-forte h-11 w-full min-w-0 rounded-md border bg-white px-2 text-sm md:h-10 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2'
</script>

<template>
  <div class="space-y-2">
    <div class="border-ligne overflow-x-auto rounded-lg border bg-white">
      <div class="md:min-w-max" :style="{ '--line-cols': gridColumns }">
        <div
          class="border-ligne text-texte-2 hidden gap-2 border-b px-2 py-2 text-sm font-medium md:grid md:[grid-template-columns:var(--line-cols)]"
        >
          <span>#</span>
          <span v-for="column in columns" :key="column.field">{{ t(column.labelKey) }}</span>
          <span></span>
        </div>
        <div
          v-for="(line, index) in modelValue"
          :key="index"
          class="border-ligne grid grid-cols-2 gap-x-2 gap-y-2 border-b p-3 text-sm last:border-0 md:items-center md:gap-y-0 md:px-2 md:py-1.5 md:[grid-template-columns:var(--line-cols)]"
          data-test="doc-line"
        >
          <span class="text-texte-3 self-center font-medium md:font-normal">
            <span class="md:hidden">{{ `${t('documents.common.line')} ` }} </span>{{ index + 1 }}
          </span>
          <div class="flex justify-end md:hidden">
            <button
              type="button"
              class="h-9 rounded-md px-2 text-sm text-red-700"
              :aria-label="t('documents.common.removeLine')"
              @click="remove(index)"
            >
              ✕
            </button>
          </div>
          <label
            v-for="(column, colIndex) in columns"
            :key="column.field"
            class="block min-w-0"
            :class="colIndex === 0 ? 'col-span-2 md:col-span-1' : ''"
          >
            <span class="text-texte-2 mb-1 block text-xs md:hidden">{{ t(column.labelKey) }}</span>
            <input
              :value="line[column.field] ?? ''"
              :type="column.type === 'number' ? 'number' : 'text'"
              :inputmode="column.type === 'number' ? 'decimal' : undefined"
              :step="column.step ?? (column.type === 'number' ? '0.01' : undefined)"
              :data-test="`line-${index}-${column.field}`"
              :class="inputClass"
              @input="update(index, column.field, ($event.target as HTMLInputElement).value)"
            />
          </label>
          <div class="hidden text-right md:block">
            <button
              type="button"
              class="text-sm text-red-700 underline"
              :aria-label="t('documents.common.removeLine')"
              @click="remove(index)"
            >
              ✕
            </button>
          </div>
        </div>
        <p v-if="!modelValue.length" class="text-texte-3 px-2 py-4 text-center text-sm">
          {{ t('documents.common.noLines') }}
        </p>
      </div>
    </div>
    <div class="flex items-center justify-between gap-3">
      <button
        type="button"
        data-test="add-line"
        class="text-bitume h-10 text-sm underline"
        @click="add"
      >
        {{ t('documents.common.addLine') }}
      </button>
      <p v-if="totalField" class="text-sm font-semibold" data-test="lines-total">
        {{ t('documents.common.total') }} : {{ formatQuantity(total) }}
      </p>
    </div>
  </div>
</template>
