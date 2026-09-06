<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const { t } = useI18n()

const resource = createResourceApi('/drivers/')
const fields = computed<FieldSchema[]>(() => [
  { key: 'name', label: t('masterData.fields.name'), type: 'text', required: true },
  { key: 'phone', label: t('masterData.fields.phone'), type: 'phone' },
  { key: 'license_number', label: t('masterData.fields.licence'), type: 'text' },
  { key: 'notes', label: t('masterData.fields.notes'), type: 'textarea' },
])
</script>

<template>
  <MasterDataView
    :title="t('masterData.titles.drivers')"
    :item-label="t('masterData.itemLabels.drivers')"
    :resource="resource"
    :fields="fields"
  />
</template>
