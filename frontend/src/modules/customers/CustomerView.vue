<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/customers/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'company_name', label: 'Company', type: 'text' },
  { key: 'phone', label: 'Phone', type: 'text' },
  { key: 'address', label: 'Address', type: 'text' },
  { key: 'contact_name', label: 'Contact', type: 'text' },
  { key: 'notes', label: 'Notes', type: 'textarea' },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Customers" :resource="resource" :fields="fields" />
</template>
