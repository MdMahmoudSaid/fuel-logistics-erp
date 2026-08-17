<script setup lang="ts">
import type { FieldSchema } from './types'

const props = defineProps<{
  fields: FieldSchema[]
  modelValue: Record<string, unknown>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, unknown>]
  submit: []
  cancel: []
}>()

function setField(key: string, value: unknown) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <form class="space-y-3" @submit.prevent="$emit('submit')">
    <div v-for="field in fields" :key="field.key" class="space-y-1">
      <label class="text-sm font-medium text-slate-600" :for="field.key">{{ field.label }}</label>

      <input
        v-if="field.type === 'text' || field.type === 'number' || field.type === 'password'"
        :id="field.key"
        :type="field.type"
        :required="field.required"
        :value="modelValue[field.key] as string | number | undefined"
        class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        @input="setField(field.key, ($event.target as HTMLInputElement).value)"
      />

      <textarea
        v-else-if="field.type === 'textarea'"
        :id="field.key"
        :value="modelValue[field.key] as string | undefined"
        class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        rows="3"
        @input="setField(field.key, ($event.target as HTMLTextAreaElement).value)"
      />

      <select
        v-else-if="field.type === 'select'"
        :id="field.key"
        :value="modelValue[field.key] as string | undefined"
        class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        @change="setField(field.key, ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </option>
      </select>

      <input
        v-else-if="field.type === 'checkbox'"
        :id="field.key"
        type="checkbox"
        :checked="Boolean(modelValue[field.key])"
        @change="setField(field.key, ($event.target as HTMLInputElement).checked)"
      />
    </div>

    <div class="flex justify-end gap-2 pt-2">
      <button type="button" class="px-3 py-2 text-sm text-slate-500" @click="$emit('cancel')">
        Cancel
      </button>
      <button type="submit" class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white">
        Save
      </button>
    </div>
  </form>
</template>
