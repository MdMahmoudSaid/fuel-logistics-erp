<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const { t } = useI18n()

const resource = createResourceApi('/trucks/')
const transporterResource = createResourceApi<{ id: number; name: string; is_internal: boolean }>(
  '/transporters/',
)
const driverResource = createResourceApi<{ id: number; name: string; phone?: string }>('/drivers/')

const transporters = ref<{ id: number; name: string; is_internal: boolean }[]>([])
const drivers = ref<{ id: number; name: string; phone?: string }[]>([])

onMounted(() => {
  Promise.all([transporterResource.list(), driverResource.list()])
    .then(([transporterData, driverData]) => {
      transporters.value = transporterData.results
      drivers.value = driverData.results
    })
    .catch(() => {})
})

// UI recette fix (2026-09-05): quick-create driver from this form, same
// idea ExpenseForm.vue already has for expense categories - the Driver
// API/model already exists, no new concept introduced.
async function createDriverQuick(payload: Record<string, unknown>) {
  const driver = await driverResource.create(payload)
  drivers.value = [...drivers.value, driver]
  return { id: driver.id, label: driver.name }
}

// Table-column definition (unfiltered - a row's own owner_transporter/
// default_driver must always resolve to a label regardless of the row's
// ownership_type, see formFields() below for the create/edit form's
// dynamically-filtered variant).
const fields = computed<FieldSchema[]>(() => [
  { key: 'internal_id', label: t('masterData.fields.internalId'), type: 'text' },
  {
    key: 'tractor_registration',
    label: t('masterData.fields.tractorReg'),
    type: 'text',
    required: true,
  },
  {
    key: 'tanker_registration',
    label: t('masterData.fields.tankerReg'),
    type: 'text',
    required: true,
  },
  {
    key: 'capacity_litres',
    label: t('masterData.fields.capacityLitres'),
    type: 'number',
    required: true,
  },
  {
    key: 'ownership_type',
    label: t('masterData.fields.ownership'),
    type: 'select',
    required: true,
    options: [
      { value: 'COMPANY_OWNED', label: t('masterData.ownershipOptions.companyOwned') },
      { value: 'EXTERNAL', label: t('masterData.ownershipOptions.external') },
    ],
  },
  {
    key: 'owner_transporter',
    label: t('masterData.fields.ownerTransporterId'),
    type: 'select',
    required: true,
    options: transporters.value.map((tr) => ({ value: String(tr.id), label: tr.name })),
  },
  {
    key: 'default_driver',
    label: t('masterData.fields.defaultDriverId'),
    type: 'select',
    options: [
      { value: '', label: t('masterData.fields.none') },
      ...drivers.value.map((d) => ({ value: String(d.id), label: d.name })),
    ],
  },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
  { key: 'notes', label: t('masterData.fields.notes'), type: 'textarea' },
])

// UI recette fix (2026-09-05): "Transporteur propriétaire" must only ever
// list transporters compatible with the truck's own ownership_type
// (COMPANY_OWNED -> internal only, EXTERNAL -> external only), mirroring
// the backend's own TruckSerializer.validate() rule - never "Aucun", the
// backend already requires a transporter in every case. Falls back to
// COMPANY_OWNED (the model's own default) when the form hasn't set
// ownership_type yet, matching what the <select> shows on a fresh create.
function formFields(form: Record<string, unknown>): FieldSchema[] {
  const ownershipType = (form.ownership_type as string | undefined) ?? 'COMPANY_OWNED'
  const compatible = transporters.value.filter((tr) =>
    ownershipType === 'COMPANY_OWNED' ? tr.is_internal : !tr.is_internal,
  )
  const transporterOptions = compatible.length
    ? compatible.map((tr) => ({ value: String(tr.id), label: tr.name }))
    : [
        {
          value: '',
          label: t(
            ownershipType === 'COMPANY_OWNED'
              ? 'masterData.noInternalTransporters'
              : 'masterData.noExternalTransporters',
          ),
        },
      ]

  return fields.value.map((field) => {
    if (field.key === 'owner_transporter') {
      return { ...field, options: transporterOptions }
    }
    if (field.key === 'default_driver') {
      return {
        ...field,
        quickCreate: {
          buttonLabel: t('masterData.quickCreateDriver'),
          errorMessage: t('masterData.quickCreateDriverError'),
          fields: [
            { key: 'name', label: t('masterData.fields.name'), type: 'text', required: true },
            { key: 'phone', label: t('masterData.fields.phone'), type: 'phone' },
          ],
          create: createDriverQuick,
        },
      }
    }
    return field
  })
}
</script>

<template>
  <MasterDataView
    :title="t('masterData.titles.trucks')"
    :item-label="t('masterData.itemLabels.trucks')"
    :resource="resource"
    :fields="fields"
    :form-fields="formFields"
  />
</template>
