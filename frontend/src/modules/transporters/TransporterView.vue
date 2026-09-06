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
  { key: 'gross_earned', label: 'Brut gagné', type: 'money', readOnly: true },
  { key: 'deductions', label: 'Déductions', type: 'money', readOnly: true },
  { key: 'advances_applied', label: 'Avances appliquées', type: 'money', readOnly: true },
  { key: 'already_paid', label: 'Déjà réglé', type: 'money', readOnly: true },
  { key: 'net_balance', label: 'Solde net', type: 'money', readOnly: true },
  { key: 'address', label: t('masterData.fields.address'), type: 'text' },
  // UI recette fix (2026-09-05): "Type de transporteur" ask - is_internal
  // already existed on the model/API (backend/apps/transport/models.py,
  // seeded by migration 0004_truck_owner_transporter_mandatory) but had no
  // form field, so it could never be set from this page.
  {
    key: 'is_internal',
    label: t('masterData.fields.isInternal'),
    type: 'checkbox',
    trueLabel: t('masterData.transporterType.internal'),
    falseLabel: t('masterData.transporterType.external'),
  },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])
</script>

<template>
  <MasterDataView
    :title="t('masterData.titles.transporters')"
    :item-label="t('masterData.itemLabels.transporters')"
    :resource="resource"
    :fields="fields"
    ledger-route-name="transporter-ledger"
  />
</template>
