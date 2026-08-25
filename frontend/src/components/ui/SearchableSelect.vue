<script setup lang="ts">
defineOptions({ name: 'UiSearchableSelect' })

import { ref, computed, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'

export interface SearchableSelectOption {
  value: string
  label: string
}

const props = withDefaults(
  defineProps<{
    modelValue: string
    options: SearchableSelectOption[]
    placeholder?: string
  }>(),
  { placeholder: '' },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const { t } = useI18n()

const query = ref('')
const open = ref(false)
const inputEl = ref<HTMLInputElement | null>(null)

const selectedLabel = computed(
  () => props.options.find((o) => o.value === props.modelValue)?.label ?? '',
)

watch(
  () => [props.modelValue, props.options] as const,
  () => {
    if (!open.value) query.value = selectedLabel.value
  },
  { immediate: true },
)

const filteredOptions = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.options
  return props.options.filter((o) => o.label.toLowerCase().includes(q))
})

function onFocus() {
  open.value = true
  query.value = ''
  nextTick(() => inputEl.value?.select())
}

function onBlur() {
  open.value = false
  query.value = selectedLabel.value
}

function select(option: SearchableSelectOption) {
  emit('update:modelValue', option.value)
  query.value = option.label
  open.value = false
}

function clear() {
  emit('update:modelValue', '')
  query.value = ''
  inputEl.value?.focus()
}
</script>

<template>
  <div class="relative">
    <input
      ref="inputEl"
      v-model="query"
      type="text"
      :placeholder="placeholder"
      class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-11 w-full rounded-lg border bg-white px-3 pe-8 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      @focus="onFocus"
      @blur="onBlur"
      @keydown.escape="($event.target as HTMLInputElement).blur()"
    />
    <button
      v-if="modelValue"
      type="button"
      class="text-texte-3 hover:text-texte-2 absolute end-2 top-1/2 -translate-y-1/2"
      tabindex="-1"
      @mousedown.prevent="clear"
    >
      ×
    </button>
    <ul
      v-if="open"
      class="border-ligne absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg border bg-white text-sm shadow-lg"
    >
      <li
        v-for="option in filteredOptions"
        :key="option.value"
        class="hover:bg-sable cursor-pointer px-3 py-2"
        @mousedown.prevent="select(option)"
      >
        {{ option.label }}
      </li>
      <li v-if="filteredOptions.length === 0" class="text-texte-3 px-3 py-2">
        {{ t('common.noResults') }}
      </li>
    </ul>
  </div>
</template>
