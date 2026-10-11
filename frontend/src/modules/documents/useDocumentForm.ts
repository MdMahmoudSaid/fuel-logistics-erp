// Shared load / save / PDF / print logic of the three document forms
// (delivery note, loading sheet, purchase order).
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { documentApi, downloadDocumentPdf, printDocumentPdf } from './api'
import { DOCUMENT_CONFIGS } from './configs'
import type { DocumentKind } from './types'

export function useDocumentForm<T extends { id: number; reference: string }>(kind: DocumentKind) {
  const config = DOCUMENT_CONFIGS[kind]
  const api = documentApi<T>(config.path)
  const route = useRoute()
  const router = useRouter()
  const { t, locale } = useI18n()

  const documentId = computed(() => (route.params.id ? Number(route.params.id) : null))
  const current = ref<T | null>(null)
  const saving = ref(false)
  const busy = ref(false)
  const error = ref('')

  async function load(): Promise<T | null> {
    if (!documentId.value) return null
    current.value = await api.get!(documentId.value)
    return current.value
  }

  async function save(payload: Partial<T>): Promise<void> {
    saving.value = true
    error.value = ''
    try {
      if (documentId.value) {
        current.value = await api.update(documentId.value, payload)
      } else {
        const created = await api.create(payload)
        router.replace({ name: config.detailRoute, params: { id: created.id } })
      }
    } catch {
      error.value = t('documents.common.saveError')
    } finally {
      saving.value = false
    }
  }

  async function withBusy(action: () => Promise<void>) {
    busy.value = true
    try {
      await action()
    } catch {
      error.value = t('documents.common.exportError')
    } finally {
      busy.value = false
    }
  }

  const pdf = () =>
    withBusy(async () => {
      if (!current.value) return
      const filename = `${config.filename}-${current.value.reference}.pdf`
      await downloadDocumentPdf(config.path, current.value.id, filename, locale.value)
    })
  const print = () =>
    withBusy(async () => {
      if (current.value) await printDocumentPdf(config.path, current.value.id, locale.value)
    })
  const back = () => router.push({ name: config.listRoute })

  return { config, documentId, current, saving, busy, error, load, save, pdf, print, back }
}

export const FIELD_CLASS =
  'border-ligne-forte h-11 w-full rounded-lg border bg-white px-3 text-sm focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'
export const LABEL_CLASS = 'text-texte-2 text-sm font-medium'
export const CARD_CLASS = 'border-ligne space-y-4 rounded-xl border bg-surface p-5'
export const today = () => new Date().toISOString().slice(0, 10)
