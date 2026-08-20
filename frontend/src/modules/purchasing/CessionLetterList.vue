<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { cessionLetterResource } from './api'
import type { CessionLetter } from './types'
import Badge from '@/components/ui/Badge.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import Button from '@/components/ui/Button.vue'

const router = useRouter()

const cessions = ref<CessionLetter[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string> = {}
    if (statusFilter.value) params.status = statusFilter.value
    const data = await cessionLetterResource.list(params)
    cessions.value = data.results
  } catch {
    error.value = 'Could not load cession letters.'
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

const STATUS_LABEL: Record<string, string> = {
  ACTIVE: 'Active',
  EXHAUSTED: 'Exhausted',
  CANCELLED: 'Cancelled',
}

function badgeVariant(status: string) {
  if (status === 'ACTIVE') return 'livre' as const
  if (status === 'EXHAUSTED') return 'ecart' as const
  if (status === 'CANCELLED') return 'critique' as const
  return 'neutre' as const
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">Cession Letters</h1>
      <Button variant="primary" @click="goToNew">New Cession</Button>
    </div>

    <div class="flex flex-wrap gap-3">
      <select
        v-model="statusFilter"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="load"
      >
        <option value="">All statuses</option>
        <option value="ACTIVE">Active</option>
        <option value="EXHAUSTED">Exhausted</option>
        <option value="CANCELLED">Cancelled</option>
      </select>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">Reference</th>
            <th class="px-3 py-2.5 text-right font-medium">Authorized (L)</th>
            <th class="px-3 py-2.5 text-right font-medium">Remaining (L)</th>
            <th class="px-3 py-2.5 font-medium">Issue date</th>
            <th class="px-3 py-2.5 font-medium">Status</th>
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
              <MonoValue :value="Number(cession.authorized_quantity).toLocaleString()" />
            </td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="Number(cession.remaining_quantity).toLocaleString()" />
            </td>
            <td class="px-3 py-2.5">{{ cession.issue_date }}</td>
            <td class="px-3 py-2.5">
              <Badge :variant="badgeVariant(cession.status)">{{
                STATUS_LABEL[cession.status]
              }}</Badge>
            </td>
          </tr>
          <tr v-if="!loading && cessions.length === 0">
            <td colspan="5" class="text-texte-3 px-3 py-8 text-center">No cession letters yet.</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
