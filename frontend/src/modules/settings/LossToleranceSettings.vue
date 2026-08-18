<script setup lang="ts">
// docs/PHASE_4_PLAN.md Etape 9: admin-only default loss tolerance setting
// (backend/apps/core/models.py LossToleranceConfig - a singleton, frozen
// onto each DeliveryControl at confirmation time so later changes here
// never rewrite past trips' figures, guide §7.2/§7.4).
import { ref, onMounted } from 'vue'
import { fetchLossTolerance, updateLossTolerance } from './api'
import type { LossToleranceConfig } from './types'

const config = ref<LossToleranceConfig | null>(null)
const toleranceLitres = ref('')
const loading = ref(true)
const error = ref('')
const saving = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    config.value = await fetchLossTolerance()
    toleranceLitres.value = config.value.tolerance_litres
  } catch {
    error.value = 'Could not load the loss tolerance setting.'
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function onSubmit() {
  saving.value = true
  error.value = ''
  try {
    config.value = await updateLossTolerance(toleranceLitres.value)
    toleranceLitres.value = config.value.tolerance_litres
  } catch {
    error.value = 'Could not save — admin rights are required to change this setting.'
  } finally {
    saving.value = false
  }
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString()
}
</script>

<template>
  <div class="max-w-md space-y-6">
    <h2 class="text-lg font-semibold text-slate-800">Loss Tolerance</h2>
    <p class="text-sm text-slate-500">
      Default tolerance (litres) applied when a discharge's loss is checked against the
      transporter's chargeable deduction. Frozen onto each delivery at the moment it is confirmed —
      changing it here only affects deliveries confirmed afterwards.
    </p>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">Loading…</p>

    <form v-else class="space-y-4 rounded border bg-white p-4" @submit.prevent="onSubmit">
      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="tolerance_litres"
          >Tolerance (L)</label
        >
        <input
          id="tolerance_litres"
          v-model="toleranceLitres"
          type="number"
          step="0.01"
          min="0"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <p class="text-xs text-slate-500">
        <template v-if="config?.updated_by_detail">
          Last updated by {{ config.updated_by_detail.email }}
          <template v-if="config.updated_at"> on {{ formatDateTime(config.updated_at) }}</template>
        </template>
        <template v-else>Not yet configured — showing the spec default (100 L).</template>
      </p>

      <div class="flex justify-end">
        <button
          type="submit"
          :disabled="saving"
          class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
    </form>
  </div>
</template>
