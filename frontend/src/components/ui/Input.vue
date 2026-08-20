<script setup lang="ts">
defineOptions({ name: 'UiInput' })

/**
 * §0.4 : zone tactile 48px min, `font-size: 16px` (imposé globalement dans
 * style.css) pour éviter le zoom auto iOS.
 */
withDefaults(
  defineProps<{
    id: string
    label?: string
    type?: string
    placeholder?: string
    error?: string
    required?: boolean
    disabled?: boolean
    autocomplete?: string
  }>(),
  {
    label: undefined,
    type: 'text',
    placeholder: undefined,
    error: undefined,
    required: false,
    disabled: false,
    autocomplete: undefined,
  },
)

const model = defineModel<string>({ default: '' })
</script>

<template>
  <div class="space-y-1.5">
    <label v-if="label" :for="id" class="text-texte-2 text-sm font-medium">
      {{ label }}
    </label>
    <input
      :id="id"
      v-model="model"
      :type="type"
      :placeholder="placeholder"
      :required="required"
      :disabled="disabled"
      :autocomplete="autocomplete"
      :aria-invalid="!!error"
      class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
      :class="error ? 'border-critique' : ''"
    />
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
  </div>
</template>
