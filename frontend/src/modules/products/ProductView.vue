<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/products/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'code', label: 'Code', type: 'text', required: true },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Products" :resource="resource" :fields="fields" />
</template>
