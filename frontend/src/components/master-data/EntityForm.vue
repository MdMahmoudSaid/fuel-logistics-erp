<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FieldSchema } from './types'
import Button from '@/components/ui/Button.vue'
import FormActions from '@/components/ui/FormActions.vue'
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

// Mise en page 2 colonnes : les champs larges (notes, création rapide
// ouverte) prennent toute la ligne, une case à cocher tient sur une ligne.
function fieldClass(field: FieldSchema): string {
  if (field.type === 'checkbox') return 'flex items-center gap-2 md:pt-7'
  // Le téléphone (indicatif + numéro) a besoin de la ligne entière pour
  // rester lisible (recette 2026-10-11).
  if (field.type === 'textarea' || field.type === 'phone' || quickCreateOpen.value[field.key])
    return 'space-y-1 md:col-span-2'
  return 'space-y-1'
}

// UI recette fix (2026-09-05): generic "+ Creer..." inline mini-form for
// any select field with a `quickCreate` config (see types.ts) - mirrors
// ExpenseForm.vue's expense-category quick-create, generalized so the
// truck form's Chauffeur field can reuse it without a bespoke page.
// Keyed by field.key (not a single shared ref) so more than one
// quick-create-enabled field could coexist on the same form someday.
const quickCreateOpen = ref<Record<string, boolean>>({})
const quickCreateValues = ref<Record<string, Record<string, unknown>>>({})
const quickCreateSaving = ref<Record<string, boolean>>({})
const quickCreateError = ref<Record<string, string>>({})

function openQuickCreate(key: string) {
  quickCreateOpen.value = { ...quickCreateOpen.value, [key]: true }
  quickCreateValues.value = { ...quickCreateValues.value, [key]: {} }
  quickCreateError.value = { ...quickCreateError.value, [key]: '' }
}

function closeQuickCreate(key: string) {
  quickCreateOpen.value = { ...quickCreateOpen.value, [key]: false }
}

function setQuickCreateField(fieldKey: string, subKey: string, value: unknown) {
  quickCreateValues.value = {
    ...quickCreateValues.value,
    [fieldKey]: { ...quickCreateValues.value[fieldKey], [subKey]: value },
  }
}

async function submitQuickCreate(field: FieldSchema) {
  if (!field.quickCreate) return
  quickCreateSaving.value = { ...quickCreateSaving.value, [field.key]: true }
  quickCreateError.value = { ...quickCreateError.value, [field.key]: '' }
  try {
    const created = await field.quickCreate.create(quickCreateValues.value[field.key] ?? {})
    // Auto-selects the newly created record and never touches any other
    // field already filled in on this form - setField() only patches
    // this one key onto the existing modelValue.
    setField(field.key, String(created.id))
    closeQuickCreate(field.key)
  } catch {
    quickCreateError.value = {
      ...quickCreateError.value,
      [field.key]: field.quickCreate.errorMessage,
    }
  } finally {
    quickCreateSaving.value = { ...quickCreateSaving.value, [field.key]: false }
  }
}
</script>

<template>
  <form class="space-y-3" @submit.prevent="$emit('submit')">
    <div class="grid grid-cols-1 gap-x-4 gap-y-3 md:grid-cols-2">
      <div v-for="field in editableFields" :key="field.key" :class="fieldClass(field)">
        <label
          class="text-texte-2 text-sm font-medium"
          :class="field.type === 'checkbox' ? 'order-2' : ''"
          :for="field.key"
          >{{ field.label }}</label
        >

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
          @input="
            setField(
              field.key,
              ($event.target as HTMLInputElement).value.replace(/\D/g, '').slice(0, 4),
            )
          "
        />

        <textarea
          v-else-if="field.type === 'textarea'"
          :id="field.key"
          :value="String(modelValue[field.key] ?? '')"
          class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          rows="2"
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

        <div v-if="field.type === 'select' && field.quickCreate" class="space-y-2">
          <button
            v-if="!quickCreateOpen[field.key]"
            type="button"
            :data-test="`quick-create-toggle-${field.key}`"
            class="text-bitume hover:text-orange text-sm font-medium"
            @click="openQuickCreate(field.key)"
          >
            {{ field.quickCreate.buttonLabel }}
          </button>
          <div v-else class="border-ligne space-y-2 rounded-lg border bg-fond p-3">
            <div v-for="qf in field.quickCreate.fields" :key="qf.key" class="space-y-1">
              <label class="sr-only" :for="`${field.key}_${qf.key}`">{{ qf.label }}</label>
              <CountryPhoneInput
                v-if="qf.type === 'phone'"
                :id="`${field.key}_${qf.key}`"
                :model-value="String(quickCreateValues[field.key]?.[qf.key] ?? '')"
                :required="qf.required"
                @update:model-value="setQuickCreateField(field.key, qf.key, $event)"
              />
              <input
                v-else
                :id="`${field.key}_${qf.key}`"
                type="text"
                :required="qf.required"
                :placeholder="qf.label"
                :value="String(quickCreateValues[field.key]?.[qf.key] ?? '')"
                class="border-ligne-forte h-10 w-full rounded-lg border bg-white px-3 text-sm focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                @input="
                  setQuickCreateField(field.key, qf.key, ($event.target as HTMLInputElement).value)
                "
              />
            </div>
            <div class="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                :loading="quickCreateSaving[field.key]"
                :data-test="`quick-create-submit-${field.key}`"
                @click="submitQuickCreate(field)"
              >
                {{ t('common.save') }}
              </Button>
              <Button type="button" variant="ghost" @click="closeQuickCreate(field.key)">
                {{ t('common.cancel') }}
              </Button>
            </div>
            <AppAlert v-if="quickCreateError[field.key]" :message="quickCreateError[field.key]!" />
          </div>
        </div>

        <input
          v-else-if="field.type === 'checkbox'"
          :id="field.key"
          type="checkbox"
          class="border-ligne-forte accent-orange h-5 w-5 rounded"
          :checked="Boolean(modelValue[field.key])"
          @change="setField(field.key, ($event.target as HTMLInputElement).checked)"
        />
      </div>
    </div>

    <FormActions>
      <Button type="button" variant="ghost" @click="$emit('cancel')">{{
        t('common.cancel')
      }}</Button>
      <Button type="submit" variant="primary">{{ t('common.save') }}</Button>
    </FormActions>
  </form>
</template>
