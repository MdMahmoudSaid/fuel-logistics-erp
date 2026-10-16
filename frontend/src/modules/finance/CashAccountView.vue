<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import { createResourceApi } from '@/api/resource'
import type { FieldSchema } from '@/components/master-data/types'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import TransferForm from './TransferForm.vue'

const { t } = useI18n()

const showTransfer = ref(false)

const resource = createResourceApi('/cash-accounts/')
const fields = computed<FieldSchema[]>(() => [
  { key: 'name', label: t('masterData.fields.name'), type: 'text', required: true },
  { key: 'location', label: t('masterData.fields.location'), type: 'text' },
  {
    key: 'currency',
    label: t('masterData.fields.currency'),
    type: 'select',
    options: [{ value: 'XOF', label: 'XOF' }],
  },
  {
    key: 'opening_balance',
    label: t('masterData.fields.openingBalance'),
    type: 'number',
    required: true,
  },
  {
    key: 'current_balance',
    label: t('masterData.fields.currentBalance'),
    type: 'number',
    readOnly: true,
  },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])
</script>

<template>
  <MasterDataView
    :title="t('masterData.titles.cashAccounts')"
    :item-label="t('masterData.itemLabels.cashAccounts')"
    :resource="resource"
    :fields="fields"
  >
    <template #header-actions="{ reload }">
      <Button variant="secondary" @click="showTransfer = true">
        {{ t('finance.transfer.open') }}
      </Button>
      <Modal
        v-if="showTransfer"
        :title="t('finance.transfer.title')"
        max-width="max-w-xl"
        @close="showTransfer = false"
      >
        <TransferForm
          source-type="cash"
          @success="
            () => {
              showTransfer = false
              reload()
            }
          "
          @cancel="showTransfer = false"
        />
      </Modal>
    </template>
  </MasterDataView>
</template>
