<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'
import { useRoles, loadRoles } from './roles'

const { t } = useI18n()

const resource = createResourceApi('/accounts/users/')
const { roles } = useRoles()

onMounted(() => {
  loadRoles().catch(() => {})
})

const fields = computed<FieldSchema[]>(() => [
  { key: 'phone', label: t('masterData.fields.phone'), type: 'phone', required: true },
  { key: 'full_name', label: t('masterData.fields.fullName'), type: 'text' },
  { key: 'email', label: t('masterData.fields.email'), type: 'text' },
  {
    key: 'role',
    label: t('masterData.fields.roleId'),
    type: 'select',
    options: roles.value.map((r) => ({ value: String(r.id), label: r.name })),
  },
  { key: 'pin', label: t('masterData.fields.pin'), type: 'pin' },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])
</script>

<template>
  <MasterDataView :title="t('masterData.titles.users')" :resource="resource" :fields="fields" />
</template>
