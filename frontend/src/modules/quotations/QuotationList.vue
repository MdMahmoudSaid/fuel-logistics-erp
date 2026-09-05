<script setup lang="ts">
// AZUR ÉNERGIE product decision 2026-09-05: "Offres commerciales" under
// Ventes. Standalone document list - no accounting/stock link, mirrors
// InvoiceList.vue's list-page pattern.
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { quotationResource, duplicateQuotation, exportQuotationPdf } from './api'
import { QUOTATION_STATUSES } from './types'
import type { Quotation, QuotationStatus } from './types'
import { formatMoney } from '@/utils/currency'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'

const router = useRouter()
const { t, locale } = useI18n()

const quotations = ref<Quotation[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref<QuotationStatus | ''>('')
const duplicatingId = ref<number | null>(null)
const exportingId = ref<number | null>(null)

async function loadQuotations() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string> = {}
    if (statusFilter.value) params.status = statusFilter.value
    const data = await quotationResource.list(params)
    quotations.value = data.results
  } catch {
    error.value = t('quotations.list.loadError')
  } finally {
    loading.value = false
  }
}

onMounted(loadQuotations)

function goToDetail(quotation: Quotation) {
  router.push({ name: 'quotation-detail', params: { id: quotation.id } })
}

async function onDuplicate(quotation: Quotation) {
  duplicatingId.value = quotation.id
  try {
    const copy = await duplicateQuotation(quotation.id)
    router.push({ name: 'quotation-detail', params: { id: copy.id } })
  } catch {
    error.value = t('quotations.list.duplicateError')
  } finally {
    duplicatingId.value = null
  }
}

async function onExportPdf(quotation: Quotation) {
  exportingId.value = quotation.id
  try {
    await exportQuotationPdf(quotation.id, quotation.reference, locale.value)
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exportingId.value = null
  }
}

function badgeVariant(status: QuotationStatus) {
  if (status === 'ACCEPTED') return 'livre' as const
  if (status === 'SENT') return 'transit' as const
  if (status === 'REJECTED' || status === 'EXPIRED') return 'critique' as const
  return 'neutre' as const
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('quotations.list.title') }}
      </h1>
      <Button variant="primary" @click="router.push({ name: 'quotation-new' })">
        {{ t('quotations.list.new') }}
      </Button>
    </div>

    <div class="flex flex-wrap gap-3">
      <select
        v-model="statusFilter"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="loadQuotations"
      >
        <option value="">{{ t('quotations.list.allStatuses') }}</option>
        <option v-for="s in QUOTATION_STATUSES" :key="s" :value="s">
          {{ t(`quotationStatus.${s}`) }}
        </option>
      </select>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">{{ t('quotations.list.table.reference') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('quotations.list.table.customer') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('quotations.list.table.issueDate') }}</th>
            <th class="px-3 py-2.5 text-right font-medium">
              {{ t('quotations.list.table.total') }}
            </th>
            <th class="px-3 py-2.5 font-medium">{{ t('quotations.list.table.status') }}</th>
            <th class="px-3 py-2.5 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="quotation in quotations"
            :key="quotation.id"
            class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
            @click="goToDetail(quotation)"
          >
            <td class="px-3 py-2.5"><MonoValue :value="quotation.reference" align="left" /></td>
            <td class="px-3 py-2.5">
              {{ quotation.customer_detail?.name || quotation.customer_name }}
            </td>
            <td class="px-3 py-2.5">{{ quotation.issue_date }}</td>
            <td class="px-3 py-2.5 text-right">
              <MonoValue :value="formatMoney(quotation.total_amount)" />
            </td>
            <td class="px-3 py-2.5">
              <Badge :variant="badgeVariant(quotation.status)">
                {{ t(`quotationStatus.${quotation.status}`) }}
              </Badge>
            </td>
            <td class="px-3 py-2.5 text-right" @click.stop>
              <span class="inline-flex items-center gap-3">
                <button
                  type="button"
                  data-test="quotation-duplicate"
                  class="text-bitume hover:text-orange text-sm underline disabled:opacity-50"
                  :disabled="duplicatingId === quotation.id"
                  @click="onDuplicate(quotation)"
                >
                  {{ t('quotations.list.duplicate') }}
                </button>
                <button
                  type="button"
                  data-test="quotation-pdf"
                  class="text-bitume hover:text-orange text-sm underline disabled:opacity-50"
                  :disabled="exportingId === quotation.id"
                  @click="onExportPdf(quotation)"
                >
                  {{ t('reports.exportPdf') }}
                </button>
              </span>
            </td>
          </tr>
          <tr v-if="!loading && quotations.length === 0">
            <td colspan="6" class="text-texte-3 px-3 py-8 text-center">
              {{ t('quotations.list.noQuotations') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
