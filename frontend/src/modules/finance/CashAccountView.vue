<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const { t } = useI18n()

const resource = createResourceApi('/cash-accounts/')
const fields = computed<FieldSchema[]>(() => [
  { key: 'name', label: t('masterData.fields.name'), type: 'text', required: true },
  { key: 'location', label: t('masterData.fields.location'), type: 'text' },
  {
    key: 'currency',
    label: t('masterData.fields.currency'),
    type: 'select',
    options: [{ value: 'XOF', label: 'XOF' }],
  },
  {
    key: 'opening_balance',
    label: t('masterData.fields.openingBalance'),
    type: 'number',
    required: true,
  },
  {
    key: 'current_balance',
    label: t('masterData.fields.currentBalance'),
    type: 'number',
    readOnly: true,
  },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])
</script>

<template>
  <MasterDataView
    :title="t('masterData.titles.cashAccounts')"
    :resource="resource"
    :fields="fields"
  />
</template>
