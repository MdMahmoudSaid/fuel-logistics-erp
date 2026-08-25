<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const { t } = useI18n()

const resource = createResourceApi('/transporters/')
const fields = computed<FieldSchema[]>(() => [
  { key: 'name', label: t('masterData.fields.name'), type: 'text', required: true },
  { key: 'company_name', label: t('masterData.fields.company'), type: 'text' },
  { key: 'phone', label: t('masterData.fields.phone'), type: 'phone' },
  { key: 'address', label: t('masterData.fields.address'), type: 'text' },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])
</script>

<template>
  <MasterDataView
    :title="t('masterData.titles.transporters')"
    :resource="resource"
    :fields="fields"
    ledger-route-name="transporter-ledger"
  />
</template>
