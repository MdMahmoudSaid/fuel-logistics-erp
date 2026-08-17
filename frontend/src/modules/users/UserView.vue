<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/accounts/users/')
const fields: FieldSchema[] = [
  { key: 'email', label: 'Email', type: 'text', required: true },
  { key: 'full_name', label: 'Full name', type: 'text' },
  { key: 'phone', label: 'Phone', type: 'text' },
  { key: 'role', label: 'Role ID', type: 'number' },
  { key: 'password', label: 'Password', type: 'password' },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Users" :resource="resource" :fields="fields" />
</template>
