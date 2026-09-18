<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { confirmDialog } from '@/composables/useConfirmDialog'
import DataTable from './DataTable.vue'
import EntityForm from './EntityForm.vue'
import Button from '@/components/ui/Button.vue'
import type { FieldSchema } from './types'
import type { ResourceApi } from '@/api/resource'
import { translateApiError, extractFieldErrors } from '@/i18n/apiErrors'

const { t } = useI18n()

const props = defineProps<{
  title: string
  resource: ResourceApi<Record<string, unknown>>
  fields: FieldSchema[]
  // UI recette fix (2026-09-05): optional - when a field's available
  // options depend on the form's own live values (e.g. Truck's
  // owner_transporter must only list transporters compatible with the
  // currently-selected ownership_type), the parent passes this instead of
  // (or in addition to) a static `fields` array. Defaults to `fields`
  // unchanged, so every other master-data page is unaffected.
  formFields?: (formValue: Record<string, unknown>) => FieldSchema[]
  ledgerRouteName?: string
  // Bug fix (recette manuelle 2026-09-06): `title` is always the plural
  // page heading ("Produits", "Fournisseurs"...), and the create/edit
  // modal used to reuse it verbatim ("Nouveau Produits" - wrong gender and
  // number in French). Optional singular label for that modal only;
  // falls back to `title` for any caller that doesn't pass it.
  itemLabel?: string
}>()

const rows = ref<Record<string, unknown>[]>([])
const showForm = ref(false)
const editingId = ref<number | null>(null)
const formValue = ref<Record<string, unknown>>({})
const error = ref('')
const showInactive = ref(false)

const columns = computed(() =>
  props.fields
    .filter((f) => f.type !== 'textarea' && f.type !== 'password' && f.type !== 'pin')
    .map((f) => ({
      key: f.key,
      label: f.label,
      type: f.type,
      options: f.options,
      trueLabel: f.trueLabel,
      falseLabel: f.falseLabel,
    })),
)

const resolvedFormFields = computed(() =>
  props.formFields ? props.formFields(formValue.value) : props.fields,
)

const hasActiveField = computed(() => props.fields.some((f) => f.key === 'is_active'))

const visibleRows = computed(() =>
  hasActiveField.value && !showInactive.value
    ? rows.value.filter((r) => r.is_active !== false)
    : rows.value,
)

async function load() {
  const data = await props.resource.list()
  // Copy defensively: some resource implementations (and this component's
  // own test doubles) return the same array reference across calls and
  // mutate it in place, which Vue's ref would otherwise treat as an
  // unchanged value and skip re-rendering.
  rows.value = [...data.results]
}

function openCreate() {
  editingId.value = null
  formValue.value = {}
  showForm.value = true
  error.value = ''
}

function openEdit(row: Record<string, unknown>) {
  editingId.value = row.id as number
  formValue.value = { ...row }
  showForm.value = true
  error.value = ''
}

async function onSubmit() {
  const payload = Object.fromEntries(
    Object.entries(formValue.value).filter(
      ([key]) => !props.fields.some((field) => field.key === key && field.readOnly),
    ),
  )
  try {
    if (editingId.value === null) {
      await props.resource.create(payload)
    } else {
      await props.resource.update(editingId.value, payload)
    }
    showForm.value = false
    await load()
  } catch (e) {
    // Surface the backend's own validation message (e.g. Phase 6's "le
    // transporteur est obligatoire pour un camion externe") instead of a
    // generic failure - the API already writes these in French
    // (translateApiError), so no per-entity mapping is needed here.
    const response = (e as { response?: { status?: number; data?: Record<string, unknown> } })
      ?.response
    const body = response?.status === 400 ? response.data : undefined
    const fieldErrors = extractFieldErrors(body)
    const generic = body?.detail ?? body?.non_field_errors
    const genericMessage = Array.isArray(generic) ? generic[0] : generic
    error.value =
      translateApiError(typeof genericMessage === 'string' ? genericMessage : undefined) ??
      Object.values(fieldErrors)[0] ??
      t('masterData.saveError')
  }
}

async function onDelete(row: Record<string, unknown>) {
  if (!(await confirmDialog(t('masterData.confirmDelete')))) {
    return
  }
  try {
    await props.resource.remove(row.id as number)
    await load()
  } catch {
    error.value = t('masterData.deleteError')
  }
}

async function onToggleActive(row: Record<string, unknown>) {
  try {
    await props.resource.update(row.id as number, { is_active: !row.is_active })
    await load()
  } catch {
    error.value = t('masterData.toggleError')
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">{{ title }}</h1>
      <div class="flex flex-wrap items-center gap-4">
        <label v-if="hasActiveField" class="text-texte-2 flex items-center gap-2 text-sm">
          <input v-model="showInactive" type="checkbox" class="accent-orange" />
          {{ t('masterData.showInactive') }}
        </label>
        <Button variant="primary" @click="openCreate">{{ t('masterData.add') }}</Button>
      </div>
    </div>

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <DataTable
        :columns="columns"
        :rows="visibleRows"
        :active-toggle="hasActiveField"
        :ledger-route-name="ledgerRouteName"
        @edit="openEdit"
        @delete="onDelete"
        @toggle-active="onToggleActive"
      />
    </div>

    <div
      v-if="showForm"
      class="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4"
    >
      <div
        class="bg-surface border-ligne max-h-[90vh] w-full max-w-md overflow-y-auto rounded-xl border p-6"
      >
        <h2 class="font-display mb-4 text-lg leading-none font-semibold uppercase">
          {{ editingId === null ? t('masterData.new') : t('masterData.edit') }}
          {{ itemLabel ?? title }}
        </h2>
        <AppAlert v-if="error" :message="error" />
        <EntityForm
          v-model="formValue"
          :fields="resolvedFormFields"
          @submit="onSubmit"
          @cancel="showForm = false"
        />
      </div>
    </div>
  </div>
</template>
