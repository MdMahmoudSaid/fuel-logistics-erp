<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'

const { t } = useI18n()

const resource = createResourceApi('/accounts/users/')
const fields = computed<FieldSchema[]>(() => [
  { key: 'email', label: t('masterData.fields.email'), type: 'text', required: true },
  { key: 'full_name', label: t('masterData.fields.fullName'), type: 'text' },
  { key: 'phone', label: t('masterData.fields.phone'), type: 'text' },
  { key: 'role', label: t('masterData.fields.roleId'), type: 'number' },
  { key: 'password', label: t('masterData.fields.password'), type: 'password' },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])
</script>

<template>
  <MasterDataView :title="t('masterData.titles.users')" :resource="resource" :fields="fields" />
</template>
