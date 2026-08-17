<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/trucks/')
const fields: FieldSchema[] = [
  { key: 'internal_id', label: 'Internal ID', type: 'text', required: true },
  { key: 'tractor_registration', label: 'Tractor Reg.', type: 'text', required: true },
  { key: 'tanker_registration', label: 'Tanker Reg.', type: 'text', required: true },
  { key: 'capacity_litres', label: 'Capacity (L)', type: 'number', required: true },
  {
    key: 'ownership_type',
    label: 'Ownership',
    type: 'select',
    required: true,
    options: [
      { value: 'COMPANY_OWNED', label: 'Company owned' },
      { value: 'EXTERNAL', label: 'External / rented' },
    ],
  },
  { key: 'owner_transporter', label: 'Owner Transporter ID', type: 'number' },
  { key: 'default_driver', label: 'Default Driver ID', type: 'number' },
  { key: 'notes', label: 'Notes', type: 'textarea' },
]
</script>

<template>
  <MasterDataView title="Trucks" :resource="resource" :fields="fields" />
</template>
