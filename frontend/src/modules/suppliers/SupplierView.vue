<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const { t } = useI18n()

const resource = createResourceApi('/suppliers/')
const fields = computed<FieldSchema[]>(() => [
  { key: 'name', label: t('masterData.fields.name'), type: 'text', required: true },
  { key: 'company_name', label: t('masterData.fields.company'), type: 'text' },
  { key: 'country', label: t('masterData.fields.country'), type: 'text' },
  { key: 'phone', label: t('masterData.fields.phone'), type: 'phone' },
  { key: 'total_purchased', label: 'Total acheté', type: 'money', readOnly: true },
  { key: 'total_paid', label: 'Total payé', type: 'money', readOnly: true },
  { key: 'outstanding_balance', label: 'Solde impayé', type: 'money', readOnly: true },
  { key: 'total_reliquat', label: 'Reliquat total', type: 'quantity', readOnly: true },
  { key: 'last_payment_date', label: 'Dernier paiement', type: 'text', readOnly: true },
  { key: 'contact_name', label: t('masterData.fields.contact'), type: 'text' },
  { key: 'notes', label: t('masterData.fields.notes'), type: 'textarea' },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])
</script>

<template>
  <MasterDataView
    :title="t('masterData.titles.suppliers')"
    :resource="resource"
    :fields="fields"
    ledger-route-name="supplier-ledger"
  />
</template>
