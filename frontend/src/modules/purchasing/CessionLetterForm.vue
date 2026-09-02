<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  cessionLetterResource,
  supplierOrderResource,
  uploadDocument,
  fetchNextCessionLetterReference,
} from './api'
import { translateApiError, extractFieldErrors } from '@/i18n/apiErrors'
import { formatQuantity } from '@/utils/currency'
import { IMAGE_UPLOAD_ACCEPT, isAllowedImageFile } from '@/utils/imageUpload'
import Button from '@/components/ui/Button.vue'
import type { CessionLetter, CessionLetterStatus, SupplierOrder } from './types'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const cessionId = computed(() => (route.params.id ? Number(route.params.id) : null))
const isNew = computed(() => cessionId.value === null)

const cession = ref<CessionLetter | null>(null)
const order = ref<SupplierOrder | null>(null)
const availableOrders = ref<SupplierOrder[]>([])

const form = ref({
  reference: '',
  supplier_order: '',
  authorized_quantity: '',
  issue_date: '',
  status: 'ACTIVE' as CessionLetterStatus,
  notes: '',
})

const saving = ref(false)
const error = ref('')
const fieldErrors = ref<Record<string, string>>({})

async function loadOrder(id: number) {
  order.value = await supplierOrderResource.get!(id)
}

onMounted(async () => {
  if (!isNew.value) {
    cession.value = await cessionLetterResource.get!(cessionId.value!)
    form.value = {
      reference: cession.value.reference,
      supplier_order: String(cession.value.supplier_order),
      authorized_quantity: cession.value.authorized_quantity,
      issue_date: cession.value.issue_date,
      status: cession.value.status,
      notes: cession.value.notes,
    }
    await loadOrder(cession.value.supplier_order)
    return
  }

  form.value.reference = await fetchNextCessionLetterReference()

  const preselected = route.query.supplier_order ? Number(route.query.supplier_order) : null
  if (preselected) {
    form.value.supplier_order = String(preselected)
    await loadOrder(preselected)
  } else {
    // No order pre-selected (arrived from top-level nav rather than a
    // supplier order's page) — let the user pick one.
    const data = await supplierOrderResource.list({ status: 'CONFIRMED' })
    availableOrders.value = data.results
  }
})

async function onOrderChange() {
  const id = Number(form.value.supplier_order)
  if (id) await loadOrder(id)
}

// --- Live allocation bar ---
// order.reliquat already excludes every non-cancelled cession, including the
// one being edited here. Add its current authorized_quantity back so the
// ceiling matches exactly what
// SupplierStockService.validate_and_lock_reliquat(exclude_cession_id=...)
// will accept server-side.
const purchased = computed(() => Number(order.value?.quantity_litres ?? 0))
const ceiling = computed(() => {
  if (!order.value) return 0
  const editingOwnAmount = !isNew.value ? Number(cession.value?.authorized_quantity ?? 0) : 0
  return Number(order.value.reliquat) + editingOwnAmount
})
const allocatedToOthers = computed(() => purchased.value - ceiling.value)
const requested = computed(() => Number(form.value.authorized_quantity) || 0)
const remainingAfterThis = computed(() => ceiling.value - requested.value)
const isOverLimit = computed(() => requested.value > ceiling.value)

function pct(value: number) {
  if (purchased.value <= 0) return 0
  return Math.max(0, Math.min(100, (value / purchased.value) * 100))
}
const allocatedPct = computed(() => pct(allocatedToOthers.value))
const requestedPct = computed(() => pct(Math.min(requested.value, Math.max(ceiling.value, 0))))
const overflowPct = computed(() => pct(Math.max(requested.value - Math.max(ceiling.value, 0), 0)))

async function onSubmit() {
  saving.value = true
  error.value = ''
  fieldErrors.value = {}
  const payload = {
    supplier_order: Number(form.value.supplier_order),
    authorized_quantity: form.value.authorized_quantity,
    issue_date: form.value.issue_date,
    status: form.value.status,
    notes: form.value.notes,
  }
  try {
    if (isNew.value) {
      const created = await cessionLetterResource.create(payload)
      await uploadSelectedDocument(created.id)
      router.replace({ name: 'cession-letter-detail', params: { id: created.id } })
    } else {
      cession.value = await cessionLetterResource.update(cessionId.value!, payload)
      await loadOrder(Number(form.value.supplier_order))
    }
  } catch (e) {
    // The server enforces the same limit under a row lock (concurrency-safe)
    // even though the bar above already warns the user client-side.
    const response = (e as { response?: { status?: number; data?: Record<string, unknown> } })
      ?.response
    const body = response?.status === 400 ? response.data : undefined
    fieldErrors.value = extractFieldErrors(body)
    const generic = body?.detail ?? body?.non_field_errors
    const genericMessage = Array.isArray(generic) ? generic[0] : generic
    error.value =
      translateApiError(typeof genericMessage === 'string' ? genericMessage : undefined) ??
      (Object.keys(fieldErrors.value).length ? '' : t('purchasing.cessionForm.saveError'))
  } finally {
    saving.value = false
  }
}

// --- Documents ---
const documentFile = ref<File | null>(null)
const uploadingDoc = ref(false)
const uploadError = ref('')

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (file && !isAllowedImageFile(file)) {
    documentFile.value = null
    input.value = ''
    uploadError.value = t('purchasing.cessionForm.imageOnlyError')
    return
  }
  documentFile.value = file
  uploadError.value = ''
}

async function uploadSelectedDocument(objectId: number) {
  if (!documentFile.value) return
  uploadingDoc.value = true
  uploadError.value = ''
  try {
    await uploadDocument({
      file: documentFile.value,
      documentType: 'cession_proof',
      contentTypeName: 'cessionletter',
      objectId,
    })
    documentFile.value = null
  } catch {
    uploadError.value = t('purchasing.cessionForm.uploadError')
  } finally {
    uploadingDoc.value = false
  }
}

async function onUploadDocument() {
  if (!documentFile.value || cessionId.value === null) return
  await uploadSelectedDocument(cessionId.value)
  cession.value = await cessionLetterResource.get!(cessionId.value)
}
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">
      {{
        isNew
          ? t('purchasing.cessionForm.newTitle')
          : t('purchasing.cessionForm.editTitle', { reference: cession?.reference ?? '' })
      }}
    </h1>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <form class="border-ligne space-y-4 rounded-xl border bg-surface p-6" @submit.prevent="onSubmit">
      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="reference">{{
          t('purchasing.cessionForm.reference')
        }}</label>
        <input
          id="reference"
          v-model="form.reference"
          disabled
          autocomplete="off"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-sable px-3.5 text-texte-2"
        />
        <p class="text-texte-3 text-xs">{{ t('purchasing.cessionForm.referenceGenerated') }}</p>
        <p v-if="fieldErrors.reference" class="text-critique text-xs">
          {{ fieldErrors.reference }}
        </p>
      </div>

      <div v-if="!route.query.supplier_order || !isNew" class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="supplier_order">{{
          t('purchasing.cessionForm.supplierOrder')
        }}</label>
        <select
          id="supplier_order"
          v-model="form.supplier_order"
          required
          :disabled="!isNew"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          @change="onOrderChange"
        >
          <option value="" disabled>{{ t('purchasing.cessionForm.selectSupplierOrder') }}</option>
          <option v-for="o in availableOrders" :key="o.id" :value="o.id">
            {{ o.reference }} — {{ o.supplier_detail?.name }} ({{ formatQuantity(o.reliquat) }}
            {{ t('purchasing.cessionForm.remainingSuffix') }})
          </option>
          <option
            v-if="order && !availableOrders.find((o) => o.id === order!.id)"
            :value="order.id"
          >
            {{ order.reference }} — {{ order.supplier_detail?.name }}
          </option>
        </select>
        <p v-if="fieldErrors.supplier_order" class="text-critique text-xs">
          {{ fieldErrors.supplier_order }}
        </p>
      </div>
      <p v-else-if="order" class="text-texte-2 text-sm">
        {{ t('purchasing.cessionForm.againstOrder') }}
        <span class="text-texte font-medium">{{ order.reference }}</span> ({{
          order.supplier_detail?.name
        }})
      </p>

      <div v-if="order" class="border-ligne space-y-2 rounded-lg border bg-sable p-3">
        <div class="text-texte-2 flex justify-between text-xs">
          <span>{{ t('purchasing.cessionForm.purchased') }} {{ formatQuantity(purchased) }}</span>
          <span
            >{{ t('purchasing.cessionForm.alreadyAllocated') }}
            {{ formatQuantity(allocatedToOthers) }}</span
          >
          <span :class="isOverLimit ? 'text-critique font-semibold' : ''">
            {{ t('purchasing.cessionForm.requested') }} {{ formatQuantity(requested) }}
          </span>
        </div>
        <div class="bg-ligne flex h-3 w-full overflow-hidden rounded-full">
          <div class="bg-texte-3" :style="{ width: allocatedPct + '%' }" />
          <div
            :class="isOverLimit ? 'bg-critique' : 'bg-livre'"
            :style="{ width: requestedPct + '%' }"
          />
          <div v-if="isOverLimit" class="bg-critique-texte" :style="{ width: overflowPct + '%' }" />
        </div>
        <p v-if="isOverLimit" class="text-critique text-sm font-medium">
          {{
            t('purchasing.cessionForm.exceedsBy', {
              amount: formatQuantity(Math.abs(remainingAfterThis)),
            })
          }}
        </p>
        <p v-else class="text-texte-2 text-sm">
          {{ t('purchasing.cessionForm.wouldRemain', { amount: formatQuantity(remainingAfterThis) }) }}
        </p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="authorized_quantity">{{
            t('purchasing.cessionForm.authorizedQuantity')
          }}</label>
          <input
            id="authorized_quantity"
            v-model="form.authorized_quantity"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            :class="isOverLimit ? 'border-critique' : ''"
          />
          <p v-if="fieldErrors.authorized_quantity" class="text-critique text-xs">
            {{ fieldErrors.authorized_quantity }}
          </p>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="issue_date">{{
            t('purchasing.cessionForm.issueDate')
          }}</label>
          <input
            id="issue_date"
            v-model="form.issue_date"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
          <p v-if="fieldErrors.issue_date" class="text-critique text-xs">
            {{ fieldErrors.issue_date }}
          </p>
        </div>

        <div v-if="!isNew" class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="status">{{
            t('purchasing.cessionForm.status')
          }}</label>
          <select
            id="status"
            v-model="form.status"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="ACTIVE">{{ t('cessionStatus.ACTIVE') }}</option>
            <option value="EXHAUSTED">{{ t('cessionStatus.EXHAUSTED') }}</option>
            <option value="CANCELLED">{{ t('cessionStatus.CANCELLED') }}</option>
          </select>
          <p v-if="fieldErrors.status" class="text-critique text-xs">{{ fieldErrors.status }}</p>
        </div>
        <div v-else class="space-y-1.5">
          <span class="text-texte-2 text-sm font-medium">
            {{ t('purchasing.cessionForm.status') }}
          </span>
          <p class="border-ligne-forte rounded-lg border bg-sable px-3.5 py-3 text-sm font-medium">
            {{ t(`cessionStatus.${form.status}`) }}
          </p>
        </div>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="notes">{{
          t('purchasing.cessionForm.notes')
        }}</label>
        <textarea
          id="notes"
          v-model="form.notes"
          rows="2"
          class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p v-if="fieldErrors.notes" class="text-critique text-xs">{{ fieldErrors.notes }}</p>
      </div>

      <div class="flex justify-end gap-2 pt-2">
        <Button variant="ghost" type="button" @click="router.back()">
          {{ t('purchasing.cessionForm.back') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('purchasing.cessionForm.saving') : t('purchasing.cessionForm.save') }}
        </Button>
      </div>
    </form>

    <section class="border-ligne space-y-3 rounded-xl border bg-surface p-6">
      <h2 class="font-display text-lg leading-none font-semibold uppercase">
        {{ t('purchasing.cessionForm.document') }}
      </h2>
      <p v-if="uploadError" class="text-critique text-sm">{{ uploadError }}</p>

      <ul class="space-y-1">
        <li v-for="doc in cession?.documents ?? []" :key="doc.id" class="text-sm">
          <a :href="doc.file" target="_blank" class="text-texte underline hover:text-texte-2">
            {{ doc.reference || doc.document_type }}
          </a>
        </li>
        <li v-if="documentFile" class="text-sm">
          {{ documentFile.name }}
        </li>
        <li v-if="!cession?.documents?.length && !documentFile" class="text-texte-3 text-sm">
          {{ t('purchasing.cessionForm.noDocument') }}
        </li>
      </ul>

      <div class="flex flex-wrap items-center gap-2 pt-2">
        <input
          type="file"
          :accept="IMAGE_UPLOAD_ACCEPT"
          class="text-texte-2 text-sm"
          @change="onFileChange"
        />
        <Button
          v-if="!isNew"
          type="button"
          variant="primary"
          :disabled="!documentFile || uploadingDoc"
          @click="onUploadDocument"
        >
          {{ uploadingDoc ? t('purchasing.cessionForm.uploading') : t('purchasing.cessionForm.upload') }}
        </Button>
      </div>
    </section>
  </div>
</template>
