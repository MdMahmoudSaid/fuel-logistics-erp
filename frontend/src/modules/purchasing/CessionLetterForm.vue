<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { cessionLetterResource, supplierOrderResource, uploadDocument } from './api'
import type { CessionLetter, CessionLetterStatus, SupplierOrder } from './types'

const route = useRoute()
const router = useRouter()

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
  const payload = {
    reference: form.value.reference,
    supplier_order: Number(form.value.supplier_order),
    authorized_quantity: form.value.authorized_quantity,
    issue_date: form.value.issue_date,
    status: form.value.status,
    notes: form.value.notes,
  }
  try {
    if (isNew.value) {
      const created = await cessionLetterResource.create(payload)
      router.replace({ name: 'cession-letter-detail', params: { id: created.id } })
    } else {
      cession.value = await cessionLetterResource.update(cessionId.value!, payload)
      await loadOrder(Number(form.value.supplier_order))
    }
  } catch (e) {
    // The server enforces the same limit under a row lock (concurrency-safe)
    // even though the bar above already warns the user client-side.
    const detail = (e as { response?: { data?: { authorized_quantity?: string[] } } })?.response
      ?.data?.authorized_quantity?.[0]
    error.value = detail || 'Could not save — check the fields and your permissions.'
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
  documentFile.value = input.files?.[0] ?? null
}

async function onUploadDocument() {
  if (!documentFile.value || cessionId.value === null) return
  uploadingDoc.value = true
  uploadError.value = ''
  try {
    await uploadDocument({
      file: documentFile.value,
      documentType: 'cession_pdf',
      contentTypeName: 'cessionletter',
      objectId: cessionId.value,
    })
    documentFile.value = null
    cession.value = await cessionLetterResource.get!(cessionId.value)
  } catch {
    uploadError.value = 'Could not upload document.'
  } finally {
    uploadingDoc.value = false
  }
}
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <h2 class="text-lg font-semibold text-slate-800">
      {{ isNew ? 'New Cession Letter' : `Cession Letter ${cession?.reference ?? ''}` }}
    </h2>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <form class="space-y-4 rounded border bg-white p-4" @submit.prevent="onSubmit">
      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="reference">Reference</label>
        <input
          id="reference"
          v-model="form.reference"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div v-if="!route.query.supplier_order || !isNew" class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="supplier_order"
          >Supplier order</label
        >
        <select
          id="supplier_order"
          v-model="form.supplier_order"
          required
          :disabled="!isNew"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-50"
          @change="onOrderChange"
        >
          <option value="" disabled>Select a supplier order</option>
          <option v-for="o in availableOrders" :key="o.id" :value="o.id">
            {{ o.reference }} — {{ o.supplier_detail?.name }} ({{
              Number(o.reliquat).toLocaleString()
            }}
            L remaining)
          </option>
          <option
            v-if="order && !availableOrders.find((o) => o.id === order!.id)"
            :value="order.id"
          >
            {{ order.reference }} — {{ order.supplier_detail?.name }}
          </option>
        </select>
      </div>
      <p v-else-if="order" class="text-sm text-slate-600">
        Against order <span class="font-medium text-slate-800">{{ order.reference }}</span> ({{
          order.supplier_detail?.name
        }})
      </p>

      <div v-if="order" class="space-y-2 rounded border border-slate-200 bg-slate-50 p-3">
        <div class="flex justify-between text-xs text-slate-500">
          <span>Purchased: {{ purchased.toLocaleString() }} L</span>
          <span>Already allocated: {{ allocatedToOthers.toLocaleString() }} L</span>
          <span :class="isOverLimit ? 'font-semibold text-red-600' : ''">
            Requested: {{ requested.toLocaleString() }} L
          </span>
        </div>
        <div class="flex h-3 w-full overflow-hidden rounded-full bg-slate-200">
          <div class="bg-slate-500" :style="{ width: allocatedPct + '%' }" />
          <div
            :class="isOverLimit ? 'bg-red-500' : 'bg-emerald-500'"
            :style="{ width: requestedPct + '%' }"
          />
          <div v-if="isOverLimit" class="bg-red-700" :style="{ width: overflowPct + '%' }" />
        </div>
        <p v-if="isOverLimit" class="text-sm font-medium text-red-600">
          Exceeds available reliquat by {{ Math.abs(remainingAfterThis).toLocaleString() }} L.
          Reduce the requested quantity before saving.
        </p>
        <p v-else class="text-sm text-slate-500">
          {{ remainingAfterThis.toLocaleString() }} L would remain available.
        </p>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="authorized_quantity"
            >Authorized quantity (L)</label
          >
          <input
            id="authorized_quantity"
            v-model="form.authorized_quantity"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            :class="isOverLimit ? 'border-red-400' : ''"
          />
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="issue_date">Issue date</label>
          <input
            id="issue_date"
            v-model="form.issue_date"
            type="date"
            required
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div v-if="!isNew" class="space-y-1">
          <label class="text-sm font-medium text-slate-600" for="status">Status</label>
          <select
            id="status"
            v-model="form.status"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="ACTIVE">Active</option>
            <option value="EXHAUSTED">Exhausted</option>
            <option value="CANCELLED">Cancelled</option>
          </select>
        </div>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="notes">Notes</label>
        <textarea
          id="notes"
          v-model="form.notes"
          rows="2"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="flex justify-end gap-2 pt-2">
        <button type="button" class="px-3 py-2 text-sm text-slate-500" @click="router.back()">
          Back
        </button>
        <button
          type="submit"
          :disabled="saving"
          class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
    </form>

    <section v-if="!isNew" class="space-y-3 rounded border bg-white p-4">
      <h3 class="text-base font-semibold text-slate-800">Cession Document</h3>
      <p v-if="uploadError" class="text-sm text-red-600">{{ uploadError }}</p>

      <ul class="space-y-1">
        <li v-for="doc in cession?.documents ?? []" :key="doc.id" class="text-sm">
          <a :href="doc.file" target="_blank" class="text-slate-700 underline hover:text-slate-900">
            {{ doc.reference || doc.document_type }}
          </a>
        </li>
        <li v-if="!cession?.documents?.length" class="text-sm text-slate-400">
          No document attached yet.
        </li>
      </ul>

      <div class="flex flex-wrap items-center gap-2 pt-2">
        <input
          type="file"
          accept="application/pdf,image/*"
          class="text-sm"
          @change="onFileChange"
        />
        <button
          type="button"
          :disabled="!documentFile || uploadingDoc"
          class="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          @click="onUploadDocument"
        >
          {{ uploadingDoc ? 'Uploading…' : 'Upload' }}
        </button>
      </div>
    </section>
  </div>
</template>
