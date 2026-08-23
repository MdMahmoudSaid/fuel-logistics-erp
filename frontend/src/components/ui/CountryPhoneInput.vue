<script setup lang="ts">
defineOptions({ name: 'UiCountryPhoneInput' })

import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  COUNTRIES,
  PRIORITY_ISO2,
  PHONE_DIGIT_RULES,
  DEFAULT_DIGIT_RULE,
  DEFAULT_ISO2,
} from '@/data/countries'

const props = withDefaults(
  defineProps<{
    id: string
    modelValue: string
    label?: string
    required?: boolean
    disabled?: boolean
    error?: string
  }>(),
  { label: undefined, required: false, disabled: false, error: undefined },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const { t, locale } = useI18n()

function parsePhone(value: string): { iso2: string; national: string } {
  if (!value) return { iso2: DEFAULT_ISO2, national: '' }
  const match = [...COUNTRIES]
    .filter((c) => value.startsWith(c.dialCode))
    .sort((a, b) => b.dialCode.length - a.dialCode.length)[0]
  if (!match) return { iso2: DEFAULT_ISO2, national: value.replace(/\D/g, '') }
  return { iso2: match.iso2, national: value.slice(match.dialCode.length) }
}

const selectedIso2 = ref(DEFAULT_ISO2)
const nationalNumber = ref('')
const query = ref('')
const open = ref(false)
const numberInput = ref<HTMLInputElement | null>(null)

watch(
  () => props.modelValue,
  (value) => {
    const parsed = parsePhone(value)
    selectedIso2.value = parsed.iso2
    nationalNumber.value = parsed.national
  },
  { immediate: true },
)

const selectedCountry = computed(
  () => COUNTRIES.find((c) => c.iso2 === selectedIso2.value) ?? COUNTRIES[0],
)

const digitRule = computed(() => PHONE_DIGIT_RULES[selectedIso2.value] ?? DEFAULT_DIGIT_RULE)

function countryName(iso2: string): string {
  try {
    return new Intl.DisplayNames([locale.value], { type: 'region' }).of(iso2) ?? iso2
  } catch {
    return iso2
  }
}

const orderedCountries = computed(() => {
  const priority = PRIORITY_ISO2.map((iso2) => COUNTRIES.find((c) => c.iso2 === iso2)).filter(
    (c): c is (typeof COUNTRIES)[number] => Boolean(c),
  )
  const rest = COUNTRIES.filter((c) => !PRIORITY_ISO2.includes(c.iso2)).sort((a, b) =>
    countryName(a.iso2).localeCompare(countryName(b.iso2), locale.value),
  )
  return [...priority, ...rest]
})

const DIACRITICS_RE = new RegExp('[̀-ͯ]', 'g')

function normalizeSearch(value: string): string {
  return value.normalize('NFD').replace(DIACRITICS_RE, '').toLowerCase()
}

const filteredCountries = computed(() => {
  const q = normalizeSearch(query.value.trim())
  if (!q) return orderedCountries.value
  return orderedCountries.value.filter(
    (c) =>
      normalizeSearch(countryName(c.iso2)).includes(q) ||
      c.dialCode.includes(q) ||
      c.iso2.toLowerCase().includes(q),
  )
})

function emitValue() {
  emit(
    'update:modelValue',
    nationalNumber.value ? selectedCountry.value.dialCode + nationalNumber.value : '',
  )
}

function onNumberInput(event: Event) {
  const digits = (event.target as HTMLInputElement).value
    .replace(/\D/g, '')
    .slice(0, digitRule.value.max)
  nationalNumber.value = digits
  emitValue()
}

function selectCountry(iso2: string) {
  selectedIso2.value = iso2
  const rule = PHONE_DIGIT_RULES[iso2] ?? DEFAULT_DIGIT_RULE
  nationalNumber.value = nationalNumber.value.slice(0, rule.max)
  open.value = false
  query.value = ''
  emitValue()
  numberInput.value?.focus()
}

function onDropdownFocus() {
  open.value = true
  query.value = ''
}

function onDropdownBlur() {
  open.value = false
  query.value = ''
}
</script>

<template>
  <div class="space-y-1.5">
    <label v-if="label" :for="id" class="text-texte-2 text-sm font-medium">{{ label }}</label>
    <div class="flex gap-2">
      <div class="relative w-36 shrink-0">
        <input
          type="text"
          :value="open ? query : `${countryName(selectedIso2)} (${selectedCountry.dialCode})`"
          class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-2.5 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          :placeholder="t('common.search')"
          :disabled="disabled"
          @focus="onDropdownFocus"
          @blur="onDropdownBlur"
          @input="query = ($event.target as HTMLInputElement).value"
          @keydown.escape="($event.target as HTMLInputElement).blur()"
        />
        <ul
          v-if="open"
          class="border-ligne absolute z-20 mt-1 max-h-56 w-56 overflow-auto rounded-lg border bg-white text-sm shadow-lg"
        >
          <li
            v-for="country in filteredCountries"
            :key="country.iso2"
            class="hover:bg-sable cursor-pointer px-3 py-2"
            @mousedown.prevent="selectCountry(country.iso2)"
          >
            {{ countryName(country.iso2) }} ({{ country.dialCode }})
          </li>
          <li v-if="filteredCountries.length === 0" class="text-texte-3 px-3 py-2">
            {{ t('common.noResults') }}
          </li>
        </ul>
      </div>
      <input
        :id="id"
        ref="numberInput"
        type="text"
        inputmode="numeric"
        :value="nationalNumber"
        :required="required"
        :disabled="disabled"
        :minlength="digitRule.min"
        :maxlength="digitRule.max"
        :pattern="`\\d{${digitRule.min},${digitRule.max}}`"
        :aria-invalid="!!error"
        class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        :class="error ? 'border-critique' : ''"
        @input="onNumberInput"
      />
    </div>
    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
  </div>
</template>
