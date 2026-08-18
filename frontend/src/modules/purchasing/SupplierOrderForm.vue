<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { supplierOrderResource, uploadDocument } from './api'
import type { SupplierOrder, SupplierOrderStatus, SupplierBrief, ProductBrief } from './types'

const route = useRoute()
const router = useRouter()

const orderId = computed(() => (route.params.id ? Number(route.params.id) : null))
const isNew = computed(() => orderId.value === null)

const suppliers = ref<SupplierBrief[]>([])
const products = ref<ProductBrief[]>([])
const order = ref<SupplierOrder | null>(null)

const form = ref({
  reference: '',
  supplier: '',
  product: '',
  purchase_date: '',
  quantity_litres: '',
  unit_price: '',
  currency: 'XOF',
  optional_costs: '',
  notes: '',
  status: 'DRAFT' as SupplierOrderStatus,
})

const saving = ref(false)
const error = ref('')

const supplierResource = createResourceApi<SupplierBrief>('/suppliers/')
const productResource = createResourceApi<ProductBrief>('/products/')

async function loadOrder() {
  if (orderId.value === null) return
  order.value = await supplierOrderResource.get!(orderId.value)
  form.value = {
    reference: order.value.reference,
    supplier: String(order.value.supplier),
    product: String(order.value.product),
    purchase_date: order.value.purchase_date,
    quantity_litres: order.value.quantity_litres,
    unit_price: order.value.unit_price,
    currency: order.value.currency,
    optional_costs: order.value.optional_costs ?? '',
    notes: order.value.notes,
    status: order.value.status,
  }
}

onMounted(async () => {
  const [supplierData, productData] = await Promise.all([
    supplierResource.list(),
    productResource.list(),
  ])
  suppliers.value = supplierData.results
  products.value = productData.results
  await loadOrder()
})

async function onSubmit() {
  saving.value = true
  error.value = ''
  const payload = {
    reference: form.value.reference,
    supplier: Number(form.value.supplier),
    product: Number(form.value.product),
    purchase_date: form.value.purchase_date,
    quantity_litres: form.value.quantity_litres,
    unit_price: form.value.unit_price,
    currency: form.value.currency,
    optional_costs: form.value.optional_costs || null,
    notes: form.value.notes,
    status: form.value.status,
  }
  try {
    if (isNew.value) {
      const created = await supplierOrderResource.create(payload)
      // Redirect into edit mode: document upload and the nested cession
      // list both need a real object_id/supplier_order to attach to.
      router.replace({ name: 'supplier-order-detail', params: { id: created.id } })
    } else {
      order.value = await supplierOrderResource.update(orderId.value!, payload)
    }
  } catch {
    error.value = 'Could not save — check the fields and your permissions.'
  } finally {
    saving.value = false
  }
}

// --- Documents ---
const documentFile = ref<File | null>(null)
const documentType = ref('purchase_contract')
const uploadingDoc = ref(false)
const uploadError = ref('')

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  documentFile.value = input.files?.[0] ?? null
}

async function onUploadDocument() {
  if (!documentFile.value || orderId.value === null) return
  uploadingDoc.value = true
  uploadError.value = ''
  try {
    await uploadDocument({
      file: documentFile.value,
      documentType: documentType.value,
      contentTypeName: 'supplierorder',
      objectId: orderId.value,
    })
    documentFile.value = null
    await loadOrder()
  } catch {
    uploadError.value = 'Could not upload document.'
  } finally {
    uploadingDoc.value = false
  }
}

function goToNewCession() {
  router.push({ name: 'cession-letter-new', query: { supplier_order: String(orderId.value) } })
}
</script>

<template>
  <div class="max-w-3xl space-y-6">
    <h2 class="text-lg font-semibold text-slate-800">
      {{ isNew ? 'New Supplier Order' : `Supplier Order ${order?.reference ?? ''}` }}
    </h2>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>

    <form class="grid grid-cols-2 gap-4 rounded border bg-white p-4" @submit.prevent="onSubmit">
      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="reference">Reference</label>
        <input
          id="reference"
          v-model="form.reference"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="status">Status</label>
        <select
          id="status"
          v-model="form.status"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="DRAFT">Draft</option>
          <option value="CONFIRMED">Confirmed</option>
          <option value="CANCELLED">Cancelled</option>
        </select>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="supplier">Supplier</label>
        <select
          id="supplier"
          v-model="form.supplier"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="" disabled>Select a supplier</option>
          <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="product">Product</label>
        <select
          id="product"
          v-model="form.product"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="" disabled>Select a product</option>
          <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="purchase_date">Purchase date</label>
        <input
          id="purchase_date"
          v-model="form.purchase_date"
          type="date"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="currency">Currency</label>
        <select
          id="currency"
          v-model="form.currency"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="XOF">XOF</option>
        </select>
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="quantity_litres">Quantity (L)</label>
        <input
          id="quantity_litres"
          v-model="form.quantity_litres"
          type="number"
          step="0.01"
          min="0.01"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="unit_price">Unit price / L</label>
        <input
          id="unit_price"
          v-model="form.unit_price"
          type="number"
          step="0.0001"
          min="0"
          required
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="space-y-1">
        <label class="text-sm font-medium text-slate-600" for="optional_costs"
          >Optional costs</label
        >
        <input
          id="optional_costs"
          v-model="form.optional_costs"
          type="number"
          step="0.01"
          min="0"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div v-if="order" class="space-y-1">
        <span class="text-sm font-medium text-slate-600">Total amount</span>
        <p class="rounded border border-transparent px-3 py-2 text-sm font-semibold text-slate-800">
          {{ Number(order.total_amount).toLocaleString() }} {{ order.currency }}
        </p>
      </div>

      <div v-if="order" class="space-y-1">
        <span class="text-sm font-medium text-slate-600">Reliquat (remaining)</span>
        <p
          class="rounded border border-transparent px-3 py-2 text-sm font-semibold"
          :class="Number(order.reliquat) <= 0 ? 'text-red-600' : 'text-emerald-700'"
        >
          {{ Number(order.reliquat).toLocaleString() }} L
        </p>
      </div>

      <div class="col-span-2 space-y-1">
        <label class="text-sm font-medium text-slate-600" for="notes">Notes</label>
        <textarea
          id="notes"
          v-model="form.notes"
          rows="2"
          class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
      </div>

      <div class="col-span-2 flex justify-end gap-2 pt-2">
        <button
          type="button"
          class="px-3 py-2 text-sm text-slate-500"
          @click="router.push({ name: 'supplier-orders' })"
        >
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
      <h3 class="text-base font-semibold text-slate-800">Documents</h3>
      <p v-if="uploadError" class="text-sm text-red-600">{{ uploadError }}</p>

      <ul class="space-y-1">
        <li v-for="doc in order?.documents ?? []" :key="doc.id" class="text-sm">
          <a :href="doc.file" target="_blank" class="text-slate-700 underline hover:text-slate-900">
            {{ doc.reference || doc.document_type }}
          </a>
          <span class="text-slate-400"> — {{ doc.document_type }}</span>
        </li>
        <li v-if="!order?.documents?.length" class="text-sm text-slate-400">
          No documents attached yet.
        </li>
      </ul>

      <div class="flex flex-wrap items-center gap-2 pt-2">
        <select v-model="documentType" class="rounded border border-slate-300 px-2 py-1.5 text-sm">
          <option value="purchase_contract">Purchase contract</option>
          <option value="receipt">Receipt</option>
          <option value="other">Other</option>
        </select>
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

    <section v-if="!isNew" class="space-y-3 rounded border bg-white p-4">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-semibold text-slate-800">Cession Letters</h3>
        <button
          class="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white"
          @click="goToNewCession"
        >
          New Cession
        </button>
      </div>

      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-b text-slate-500">
            <th class="px-2 py-1.5 font-medium">Reference</th>
            <th class="px-2 py-1.5 font-medium text-right">Authorized (L)</th>
            <th class="px-2 py-1.5 font-medium text-right">Remaining (L)</th>
            <th class="px-2 py-1.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="cession in order?.cessions ?? []"
            :key="cession.id"
            class="border-b last:border-0"
          >
            <td class="px-2 py-1.5">{{ cession.reference }}</td>
            <td class="px-2 py-1.5 text-right">
              {{ Number(cession.authorized_quantity).toLocaleString() }}
            </td>
            <td class="px-2 py-1.5 text-right">
              {{ Number(cession.remaining_quantity).toLocaleString() }}
            </td>
            <td class="px-2 py-1.5">{{ cession.status }}</td>
          </tr>
          <tr v-if="!order?.cessions?.length">
            <td colspan="4" class="px-2 py-4 text-center text-slate-400">
              No cession letters yet.
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
