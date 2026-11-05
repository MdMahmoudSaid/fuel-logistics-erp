<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { confirmDialog } from '@/composables/useConfirmDialog'
import DataTable from './DataTable.vue'
import EntityForm from './EntityForm.vue'
import Button from '@/components/ui/Button.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import type { AccountStatus, FieldSchema } from './types'
import { statusPayload } from './statusActions'
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
  // Customers, suppliers and transporters only: adds the "Anciens" group
  // (no longer trading, balance still open).
  legacySupport?: boolean
}>()

const rows = ref<Record<string, unknown>[]>([])
const showForm = ref(false)
const editingId = ref<number | null>(null)
const formValue = ref<Record<string, unknown>>({})
const error = ref('')
const statusTab = ref<AccountStatus>('active')

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

// With the Actifs / Anciens / Inactifs switch the status is changed from the
// list, never from the form (a stale checkbox could fight the "Ancien" flag).
const resolvedFormFields = computed(() => {
  const base = props.formFields ? props.formFields(formValue.value) : props.fields
  return props.legacySupport ? base.filter((f) => f.key !== 'is_active') : base
})

const hasActiveField = computed(() => props.fields.some((f) => f.key === 'is_active'))

function rowStatus(row: Record<string, unknown>): AccountStatus {
  if (props.legacySupport && row.is_legacy === true) return 'legacy'
  return row.is_active === false ? 'inactive' : 'active'
}

const statusCounts = computed(() => {
  const counts: Record<AccountStatus, number> = { active: 0, legacy: 0, inactive: 0 }
  for (const row of rows.value) counts[rowStatus(row)]++
  return counts
})

const statusOptions = computed(() => {
  const options: { value: AccountStatus; label: string; count: number }[] = [
    { value: 'active', label: t('masterData.tabActive'), count: statusCounts.value.active },
  ]
  if (props.legacySupport)
    options.push({
      value: 'legacy',
      label: t('masterData.tabLegacy'),
      count: statusCounts.value.legacy,
    })
  options.push({
    value: 'inactive',
    label: t('masterData.tabInactive'),
    count: statusCounts.value.inactive,
  })
  return options
})

const visibleRows = computed(() =>
  hasActiveField.value ? rows.value.filter((r) => rowStatus(r) === statusTab.value) : rows.value,
)

async function load() {
  // Every page: the API pages by 25, and a list (with its Actifs / Inactifs
  // counts) that stops at the first page silently hides the other records.
  const all: Record<string, unknown>[] = []
  for (let page = 1; page <= 200; page++) {
    const data = await props.resource.list(page === 1 ? undefined : { page })
    all.push(...data.results)
    if (!data.next) break
  }
  // A fresh array: some resource implementations (and this component's own
  // test doubles) return the same array reference across calls and mutate it
  // in place, which Vue's ref would otherwise treat as unchanged.
  rows.value = all
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
      ([key]) =>
        !props.fields.some((field) => field.key === key && field.readOnly) &&
        !(props.legacySupport && (key === 'is_active' || key === 'is_legacy')),
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

async function onSetStatus(row: Record<string, unknown>, status: AccountStatus) {
  const payload = statusPayload(status, props.legacySupport)
  try {
    await props.resource.update(row.id as number, payload)
    await load()
    error.value = ''
  } catch (e) {
    // e.g. "balance not zero: cannot be deactivated, move to Ancien" - the
    // backend wording is shown as-is.
    const response = (e as { response?: { status?: number; data?: Record<string, unknown> } })
      ?.response
    const body = response?.status === 400 ? response.data : undefined
    const first = Object.values(extractFieldErrors(body))[0]
    error.value = first ?? t('masterData.toggleError')
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">{{ title }}</h1>
      <div class="flex flex-wrap items-center gap-4">
        <SegmentedControl
          v-if="hasActiveField"
          v-model="statusTab"
          :options="statusOptions"
          :aria-label="t('masterData.statusFilter')"
        />
        <slot name="header-actions" :reload="load" />
        <Button variant="primary" @click="openCreate">{{ t('masterData.add') }}</Button>
      </div>
    </div>

    <AppAlert v-if="error && !showForm" :message="error" />

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <DataTable
        :columns="columns"
        :rows="visibleRows"
        :active-toggle="hasActiveField"
        :legacy-support="legacySupport"
        :ledger-route-name="ledgerRouteName"
        @edit="openEdit"
        @delete="onDelete"
        @set-status="onSetStatus"
      />
    </div>

    <div
      v-if="showForm"
      class="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4"
    >
      <div
        class="bg-surface border-ligne max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border p-6"
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
