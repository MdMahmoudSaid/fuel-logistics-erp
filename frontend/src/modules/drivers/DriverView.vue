<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/drivers/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'phone', label: 'Phone', type: 'text' },
  { key: 'license_number', label: 'Licence', type: 'text' },
  { key: 'notes', label: 'Notes', type: 'textarea' },
]
</script>

<template>
  <MasterDataView title="Drivers" :resource="resource" :fields="fields" />
</template>
