<script setup lang="ts">
// One list page for the four commercial documents - proformas, delivery
// notes, loading sheets, purchase orders (spec 2026-10-11
// documents-commerciaux §1). What differs per kind lives in configs.ts.
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { apiClient } from '@/api/client'
import AppAlert from '@/components/ui/AppAlert.vue'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import { confirmDialog } from '@/composables/useConfirmDialog'
import { formatMoney, formatQuantity } from '@/utils/currency'
import { documentApi, downloadDocumentPdf, listAll, printDocumentPdf } from './api'
import { DOCUMENT_CONFIGS } from './configs'
import type { DocumentKind, DocumentRow } from './types'

const props = defineProps<{ kind: DocumentKind }>()

const router = useRouter()
const { t, locale } = useI18n()

const config = computed(() => DOCUMENT_CONFIGS[props.kind])
const rows = ref<DocumentRow[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref('')
const busyId = ref<number | null>(null)

const label = (key: string) => t(`documents.${config.value.i18n}.${key}`)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string> = {}
    if (statusFilter.value) params.status = statusFilter.value
    rows.value = await listAll(documentApi<DocumentRow>(config.value.path), params)
  } catch {
    error.value = t('documents.common.loadError')
  } finally {
    loading.value = false
  }
}

watch(
  () => props.kind,
  () => {
    statusFilter.value = ''
    load()
  },
  { immediate: true },
)

function displayValue(row: DocumentRow): string {
  const raw = row[config.value.value.field] as string | number | undefined
  if (raw === undefined || raw === null) return ''
  return config.value.value.kind === 'money' ? formatMoney(raw) : formatQuantity(raw)
}

function open(row: DocumentRow) {
  router.push({ name: config.value.detailRoute, params: { id: row.id } })
}

async function run(row: DocumentRow, action: () => Promise<unknown>) {
  busyId.value = row.id
  error.value = ''
  try {
    await action()
  } catch {
    error.value = t('documents.common.exportError')
  } finally {
    busyId.value = null
  }
}

const onPdf = (row: DocumentRow) =>
  run(row, () =>
    downloadDocumentPdf(
      config.value.path,
      row.id,
      `${config.value.filename}-${row.reference}.pdf`,
      locale.value,
    ),
  )
const onPrint = (row: DocumentRow) =>
  run(row, () => printDocumentPdf(config.value.path, row.id, locale.value))

async function onDuplicate(row: DocumentRow) {
  const { data } = await apiClient.post<{ id: number }>(
    `${config.value.duplicatePath}${row.id}/duplicate/`,
  )
  router.push({ name: config.value.detailRoute, params: { id: data.id } })
}

async function onDelete(row: DocumentRow) {
  if (!(await confirmDialog(t('documents.common.deleteConfirm', { reference: row.reference }))))
    return
  try {
    await documentApi(config.value.path).remove(row.id)
    await load()
  } catch {
    error.value = t('documents.common.deleteError')
  }
}

const actionClass = 'text-bitume hover:text-orange text-sm underline disabled:opacity-50'
const cardActionClass =
  'border-ligne-forte text-bitume h-10 rounded-lg border bg-white px-3 text-sm disabled:opacity-50'
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ label('title') }}
      </h1>
      <Button variant="primary" data-test="doc-new" @click="router.push({ name: config.newRoute })">
        {{ label('new') }}
      </Button>
    </div>

    <div v-if="config.statuses" class="flex flex-wrap gap-3">
      <select
        v-model="statusFilter"
        data-test="doc-status-filter"
        class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
        @change="load"
      >
        <option value="">{{ t('documents.common.allStatuses') }}</option>
        <option v-for="s in config.statuses.values" :key="s" :value="s">
          {{ t(`${config.statuses.labelPrefix}${s}`) }}
        </option>
      </select>
    </div>

    <AppAlert v-if="error" :message="error" />
    <p v-if="loading" class="text-texte-3 text-sm">{{ t('documents.common.loading') }}</p>

    <!-- Téléphone : une carte par document, actions en boutons tactiles. -->
    <div class="space-y-3 md:hidden">
      <div
        v-for="row in rows"
        :key="`card-${row.id}`"
        class="border-ligne cursor-pointer rounded-xl border bg-white p-4"
        @click="open(row)"
      >
        <div class="flex items-start justify-between gap-3">
          <MonoValue :value="row.reference" align="left" class="font-semibold" />
          <span
            v-if="config.statuses"
            class="bg-sable text-texte-2 shrink-0 rounded-full px-2.5 py-0.5 text-xs"
          >
            {{ t(`${config.statuses.labelPrefix}${row.status}`) }}
          </span>
        </div>
        <p class="text-texte mt-1 text-sm">{{ config.partner(row) }}</p>
        <div class="mt-2 flex items-end justify-between gap-3">
          <span class="text-texte-3 text-xs">{{ row[config.dateField] }}</span>
          <MonoValue :value="displayValue(row)" class="text-base" />
        </div>
        <div class="border-ligne mt-3 flex flex-wrap gap-2 border-t pt-3" @click.stop>
          <button
            v-if="config.duplicatePath"
            type="button"
            :class="cardActionClass"
            @click="onDuplicate(row)"
          >
            {{ t('documents.common.duplicate') }}
          </button>
          <button
            type="button"
            :class="cardActionClass"
            :disabled="busyId === row.id"
            @click="onPdf(row)"
          >
            {{ t('documents.common.pdf') }}
          </button>
          <button
            type="button"
            :class="cardActionClass"
            :disabled="busyId === row.id"
            @click="onPrint(row)"
          >
            {{ t('documents.common.print') }}
          </button>
          <button
            type="button"
            class="ms-auto h-10 rounded-lg px-3 text-sm text-red-700"
            @click="onDelete(row)"
          >
            {{ t('documents.common.delete') }}
          </button>
        </div>
      </div>
      <p
        v-if="!loading && rows.length === 0"
        class="border-ligne text-texte-3 rounded-xl border bg-white px-3 py-8 text-center text-sm"
      >
        {{ label('empty') }}
      </p>
    </div>

    <div class="border-ligne hidden overflow-x-auto rounded-xl border bg-white md:block">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">{{ t('documents.common.reference') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ label('partner') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('documents.common.date') }}</th>
            <th class="px-3 py-2.5 text-right font-medium">
              {{
                config.value.kind === 'money'
                  ? t('documents.common.amount')
                  : t('documents.common.litres')
              }}
            </th>
            <th v-if="config.statuses" class="px-3 py-2.5 font-medium">
              {{ t('documents.common.status') }}
            </th>
            <th class="px-3 py-2.5 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.id"
            class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
            @click="open(row)"
          >
            <td class="px-3 py-2.5"><MonoValue :value="row.reference" align="left" /></td>
            <td class="px-3 py-2.5">{{ config.partner(row) }}</td>
            <td class="px-3 py-2.5">{{ row[config.dateField] }}</td>
            <td class="px-3 py-2.5 text-right"><MonoValue :value="displayValue(row)" /></td>
            <td v-if="config.statuses" class="px-3 py-2.5">
              {{ t(`${config.statuses.labelPrefix}${row.status}`) }}
            </td>
            <td class="px-3 py-2.5 text-right" @click.stop>
              <span class="inline-flex items-center gap-3">
                <button
                  v-if="config.duplicatePath"
                  type="button"
                  data-test="doc-duplicate"
                  :class="actionClass"
                  @click="onDuplicate(row)"
                >
                  {{ t('documents.common.duplicate') }}
                </button>
                <button
                  type="button"
                  data-test="doc-pdf"
                  :class="actionClass"
                  :disabled="busyId === row.id"
                  @click="onPdf(row)"
                >
                  {{ t('documents.common.pdf') }}
                </button>
                <button
                  type="button"
                  data-test="doc-print"
                  :class="actionClass"
                  :disabled="busyId === row.id"
                  @click="onPrint(row)"
                >
                  {{ t('documents.common.print') }}
                </button>
                <button
                  type="button"
                  data-test="doc-delete"
                  class="text-sm text-red-700 underline"
                  @click="onDelete(row)"
                >
                  {{ t('documents.common.delete') }}
                </button>
              </span>
            </td>
          </tr>
          <tr v-if="!loading && rows.length === 0">
            <td colspan="6" class="text-texte-3 px-3 py-8 text-center">{{ label('empty') }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
