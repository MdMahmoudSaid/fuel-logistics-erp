<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/transporters/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'company_name', label: 'Company', type: 'text' },
  { key: 'phone', label: 'Phone', type: 'text' },
  { key: 'address', label: 'Address', type: 'text' },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Transporters" :resource="resource" :fields="fields" />
</template>
