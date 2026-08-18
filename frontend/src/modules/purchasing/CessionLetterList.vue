<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { cessionLetterResource } from './api'
import type { CessionLetter } from './types'

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

const STATUS_BADGE: Record<string, string> = {
  ACTIVE: 'bg-emerald-100 text-emerald-700',
  EXHAUSTED: 'bg-amber-100 text-amber-700',
  CANCELLED: 'bg-red-100 text-red-700',
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">Cession Letters</h2>
      <button
        class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white"
        @click="goToNew"
      >
        New Cession
      </button>
    </div>

    <div class="flex flex-wrap gap-3 rounded border bg-white p-3">
      <select
        v-model="statusFilter"
        class="rounded border border-slate-300 px-2 py-1.5 text-sm"
        @change="load"
      >
        <option value="">All statuses</option>
        <option value="ACTIVE">Active</option>
        <option value="EXHAUSTED">Exhausted</option>
        <option value="CANCELLED">Cancelled</option>
      </select>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <div class="overflow-x-auto rounded border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-b text-slate-500">
            <th class="px-3 py-2 font-medium">Reference</th>
            <th class="px-3 py-2 font-medium text-right">Authorized (L)</th>
            <th class="px-3 py-2 font-medium text-right">Remaining (L)</th>
            <th class="px-3 py-2 font-medium">Issue date</th>
            <th class="px-3 py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="cession in cessions"
            :key="cession.id"
            class="cursor-pointer border-b last:border-0 hover:bg-slate-50"
            @click="goToDetail(cession)"
          >
            <td class="px-3 py-2 font-medium text-slate-800">{{ cession.reference }}</td>
            <td class="px-3 py-2 text-right">
              {{ Number(cession.authorized_quantity).toLocaleString() }}
            </td>
            <td class="px-3 py-2 text-right">
              {{ Number(cession.remaining_quantity).toLocaleString() }}
            </td>
            <td class="px-3 py-2">{{ cession.issue_date }}</td>
            <td class="px-3 py-2">
              <span
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :class="STATUS_BADGE[cession.status]"
              >
                {{ cession.status }}
              </span>
            </td>
          </tr>
          <tr v-if="!loading && cessions.length === 0">
            <td colspan="5" class="px-3 py-6 text-center text-slate-400">
              No cession letters yet.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
