<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const { t } = useI18n()

const resource = createResourceApi('/products/')
const fields = computed<FieldSchema[]>(() => [
  { key: 'name', label: t('masterData.fields.name'), type: 'text', required: true },
  { key: 'code', label: t('masterData.fields.code'), type: 'text', required: true },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])
</script>

<template>
  <MasterDataView
    :title="t('masterData.titles.products')"
    :item-label="t('masterData.itemLabels.products')"
    :resource="resource"
    :fields="fields"
  />
</template>
