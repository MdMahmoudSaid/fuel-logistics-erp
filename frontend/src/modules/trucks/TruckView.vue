<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const { t } = useI18n()

const resource = createResourceApi('/trucks/')
const transporterResource = createResourceApi<{ id: number; name: string }>('/transporters/')
const driverResource = createResourceApi<{ id: number; name: string }>('/drivers/')

const transporters = ref<{ id: number; name: string }[]>([])
const drivers = ref<{ id: number; name: string }[]>([])

onMounted(async () => {
  const [transporterData, driverData] = await Promise.all([
    transporterResource.list(),
    driverResource.list(),
  ])
  transporters.value = transporterData.results
  drivers.value = driverData.results
})

const fields = computed<FieldSchema[]>(() => [
  { key: 'internal_id', label: t('masterData.fields.internalId'), type: 'text' },
  { key: 'tractor_registration', label: t('masterData.fields.tractorReg'), type: 'text', required: true },
  { key: 'tanker_registration', label: t('masterData.fields.tankerReg'), type: 'text', required: true },
  { key: 'capacity_litres', label: t('masterData.fields.capacityLitres'), type: 'number', required: true },
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
    options: [
      { value: '', label: t('masterData.fields.none') },
      ...transporters.value.map((tr) => ({ value: String(tr.id), label: tr.name })),
    ],
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
</script>

<template>
  <MasterDataView :title="t('masterData.titles.trucks')" :resource="resource" :fields="fields" />
</template>
