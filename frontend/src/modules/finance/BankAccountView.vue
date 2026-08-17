<script setup lang="ts">
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const resource = createResourceApi('/bank-accounts/')
const fields: FieldSchema[] = [
  { key: 'name', label: 'Name', type: 'text', required: true },
  { key: 'bank_name', label: 'Bank', type: 'text' },
  { key: 'account_number', label: 'Account Number', type: 'text' },
  { key: 'currency', label: 'Currency', type: 'select', options: [{ value: 'XOF', label: 'XOF' }] },
  { key: 'opening_balance', label: 'Opening Balance', type: 'number', required: true },
  { key: 'is_active', label: 'Active', type: 'checkbox' },
]
</script>

<template>
  <MasterDataView title="Bank Accounts" :resource="resource" :fields="fields" />
</template>
