<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { cessionLetterResource } from './api'
import { formatQuantity } from '@/utils/currency'
import type { CessionLetter } from './types'
import Badge from '@/components/ui/Badge.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'

const router = useRouter()
const { t } = useI18n()

const cessions = ref<CessionLetter[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref('')
const previewUrl = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string> = {}
    if (statusFilter.value) params.status = statusFilter.value
    const data = await cessionLetterResource.list(params)
    cessions.value = data.results
  } catch {
    error.value = t('purchasing.cessionList.loadError')
  } finally {
    loading.value = false
  }
}

onMounted(load)

function goToNew() {
  router.push({ name: 'cession-letter-new' })
}

function goToDetail(cession: CessionLetter) {
  router.push({ name: 'cession-letter-detail', params: { id: cession.id } })
}

function badgeVariant(status: string) {
  if (status === 'ACTIVE') return 'livre' as const
  if (status === 'EXHAUSTED') return 'ecart' as const
  if (status === 'CANCELLED') return 'critique' as const
  return 'neutre' as const
}

function proofUrl(cession: CessionLetter) {
  return cession.documents[0]?.file ?? null
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('purchasing.cessionList.title') }}
      </h1>
      <Button variant="primary" @click="goToNew">{{ t('purchasing.cessionList.newCession') }}</Button>
    </div>

    <div class="flex flex-wrap gap-3">
      <select
        v-model="statusFilter"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="load"
      >
        <option value="">{{ t('purchasing.cessionList.allStatuses') }}</option>
        <option value="ACTIVE">{{ t('cessionStatus.ACTIVE') }}</option>
        <option value="EXHAUSTED">{{ t('cessionStatus.EXHAUSTED') }}</option>
        <option value="CANCELLED">{{ t('cessionStatus.CANCELLED') }}</option>
      </select>
    </div>

    <AppAlert v-if="error" :message="error" />

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">{{ t('purchasing.cessionList.table.reference') }}</th>
            <th class="px-3 py-2.5 text-right font-medium">
              {{ t('purchasing.cessionList.table.authorized') }}
            </th>
            <th class="px-3 py-2.5 text-right font-medium">
              {{ t('purchasing.cessionList.table.remaining') }}
            </th>
            <th class="px-3 py-2.5 font-medium">{{ t('purchasing.cessionList.table.issueDate') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('purchasing.cessionList.table.status') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('purchasing.cessionList.table.proof') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="cession in cessions"
            :key="cession.id"
            class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
            @click="goToDetail(cession)"
          >
            <td class="px-3 py-2.5"><MonoValue :value="cession.reference" align="left" /></td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="formatQuantity(cession.authorized_quantity)" />
            </td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="formatQuantity(cession.remaining_quantity)" />
            </td>
            <td class="px-3 py-2.5">{{ cession.issue_date }}</td>
            <td class="px-3 py-2.5">
              <Badge :variant="badgeVariant(cession.status)">{{
                t(`cessionStatus.${cession.status}`)
              }}</Badge>
            </td>
            <td class="px-3 py-2.5">
              <button
                v-if="proofUrl(cession)"
                type="button"
                class="text-bitume underline"
                @click.stop="previewUrl = proofUrl(cession)"
              >
                {{ t('purchasing.cessionList.viewProof') }}
              </button>
              <span v-else class="text-texte-3">—</span>
            </td>
          </tr>
          <tr v-if="!loading && cessions.length === 0">
            <td colspan="6" class="text-texte-3 px-3 py-8 text-center">
              {{ t('purchasing.cessionList.noCessions') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Modal
      v-if="previewUrl"
      :title="t('purchasing.cessionList.table.proof')"
      max-width="max-w-3xl"
      @close="previewUrl = null"
    >
      <img :src="previewUrl" class="max-h-[80vh] w-full rounded-lg object-contain" />
      <div class="mt-4 flex justify-end">
        <Button variant="ghost" @click="previewUrl = null">{{ t('common.close') }}</Button>
      </div>
    </Modal>
  </div>
</template>
