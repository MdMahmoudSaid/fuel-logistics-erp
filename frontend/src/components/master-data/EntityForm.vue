<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FieldSchema } from './types'
import Button from '@/components/ui/Button.vue'
import CountryPhoneInput from '@/components/ui/CountryPhoneInput.vue'
import { blockNonDigitInput } from '@/utils/numeric-input'

const { t } = useI18n()

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

function inputValue(key: string): string | number | undefined {
  const value = props.modelValue[key]
  return typeof value === 'string' || typeof value === 'number' ? value : undefined
}

const editableFields = computed(() => props.fields.filter((field) => !field.readOnly))
</script>

<template>
  <form class="space-y-3" @submit.prevent="$emit('submit')">
    <div v-for="field in editableFields" :key="field.key" class="space-y-1.5">
      <label class="text-texte-2 text-sm font-medium" :for="field.key">{{ field.label }}</label>

      <input
        v-if="field.type === 'text' || field.type === 'number' || field.type === 'password'"
        :id="field.key"
        :type="field.type"
        :required="field.required"
        :value="inputValue(field.key)"
        class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        @input="setField(field.key, ($event.target as HTMLInputElement).value)"
      />

      <CountryPhoneInput
        v-else-if="field.type === 'phone'"
        :id="field.key"
        :model-value="String(modelValue[field.key] ?? '')"
        :required="field.required"
        @update:model-value="setField(field.key, $event)"
      />

      <input
        v-else-if="field.type === 'pin'"
        :id="field.key"
        type="password"
        inputmode="numeric"
        pattern="\d{4}"
        minlength="4"
        maxlength="4"
        :required="field.required"
        :value="String(modelValue[field.key] ?? '')"
        class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        @beforeinput="blockNonDigitInput"
        @input="setField(field.key, ($event.target as HTMLInputElement).value.replace(/\D/g, '').slice(0, 4))"
      />

      <textarea
        v-else-if="field.type === 'textarea'"
        :id="field.key"
        :value="String(modelValue[field.key] ?? '')"
        class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        rows="3"
        @input="setField(field.key, ($event.target as HTMLTextAreaElement).value)"
      />

      <select
        v-else-if="field.type === 'select'"
        :id="field.key"
        :value="String(modelValue[field.key] ?? '')"
        class="border-ligne-forte text-texte focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
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
        class="border-ligne-forte accent-orange h-5 w-5 rounded"
        :checked="Boolean(modelValue[field.key])"
        @change="setField(field.key, ($event.target as HTMLInputElement).checked)"
      />
    </div>

    <div class="flex justify-end gap-2 pt-2">
      <Button type="button" variant="ghost" @click="$emit('cancel')">{{ t('common.cancel') }}</Button>
      <Button type="submit" variant="primary">{{ t('common.save') }}</Button>
    </div>
  </form>
</template>
