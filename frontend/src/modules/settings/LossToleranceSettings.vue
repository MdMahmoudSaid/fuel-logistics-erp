<script setup lang="ts">
// docs/PHASE_4_PLAN.md Etape 9: admin-only default loss tolerance setting
// (backend/apps/core/models.py LossToleranceConfig - a singleton, frozen
// onto each DeliveryControl at confirmation time so later changes here
// never rewrite past trips' figures, guide §7.2/§7.4).
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { fetchLossTolerance, updateLossTolerance } from './api'
import type { LossToleranceConfig } from './types'
import Button from '@/components/ui/Button.vue'

const { t } = useI18n()

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
    error.value = t('settings.lossTolerance.loadError')
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
    error.value = t('settings.lossTolerance.saveError')
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
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">
      {{ t('settings.lossTolerance.title') }}
    </h1>
    <p class="text-texte-2 text-sm">
      {{ t('settings.lossTolerance.description') }}
    </p>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <form
      v-else
      class="border-ligne space-y-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="tolerance_litres">{{
          t('settings.lossTolerance.tolerance')
        }}</label>
        <input
          id="tolerance_litres"
          v-model="toleranceLitres"
          type="number"
          step="0.01"
          min="0"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>

      <p class="text-texte-3 text-xs">
        <template v-if="config?.updated_by_detail">
          {{ t('settings.lossTolerance.lastUpdatedBy', { email: config.updated_by_detail.email }) }}
          <template v-if="config.updated_at">
            {{ t('settings.lossTolerance.on') }} {{ formatDateTime(config.updated_at) }}</template
          >
        </template>
        <template v-else>{{ t('settings.lossTolerance.notConfigured') }}</template>
      </p>

      <div class="flex justify-end">
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('settings.lossTolerance.saving') : t('settings.lossTolerance.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>
