<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const { t } = useI18n()

const resource = createResourceApi('/trucks/')
const fields = computed<FieldSchema[]>(() => [
  { key: 'internal_id', label: t('masterData.fields.internalId'), type: 'text', required: true },
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
  { key: 'owner_transporter', label: t('masterData.fields.ownerTransporterId'), type: 'number' },
  { key: 'default_driver', label: t('masterData.fields.defaultDriverId'), type: 'number' },
  { key: 'notes', label: t('masterData.fields.notes'), type: 'textarea' },
])
</script>

<template>
  <MasterDataView :title="t('masterData.titles.trucks')" :resource="resource" :fields="fields" />
</template>
