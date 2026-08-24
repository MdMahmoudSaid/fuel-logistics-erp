<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { translateApiError, extractFieldErrors } from '@/i18n/apiErrors'
import { supplierOrderResource, uploadDocument, fetchNextSupplierOrderReference } from './api'
import Button from '@/components/ui/Button.vue'
import type { SupplierOrder, SupplierOrderStatus, SupplierBrief, ProductBrief } from './types'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

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
const fieldErrors = ref<Record<string, string>>({})

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
  if (isNew.value) {
    form.value.reference = await fetchNextSupplierOrderReference()
  }
  await loadOrder()
})

async function onSubmit() {
  saving.value = true
  error.value = ''
  fieldErrors.value = {}
  const payload = {
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
  } catch (e) {
    const response = (e as { response?: { status?: number; data?: Record<string, unknown> } })
      ?.response
    const body = response?.status === 400 ? response.data : undefined
    if (body) {
      fieldErrors.value = extractFieldErrors(body)
      const generic = body.detail ?? body.non_field_errors
      const genericMessage = Array.isArray(generic) ? generic[0] : generic
      error.value =
        translateApiError(typeof genericMessage === 'string' ? genericMessage : undefined) ??
        (Object.keys(fieldErrors.value).length ? '' : t('purchasing.orderForm.saveError'))
    } else {
      error.value = t('purchasing.orderForm.saveError')
    }
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
    uploadError.value = t('purchasing.orderForm.uploadError')
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
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">
      {{
        isNew
          ? t('purchasing.orderForm.newTitle')
          : t('purchasing.orderForm.editTitle', { reference: order?.reference ?? '' })
      }}
    </h1>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>

    <form
      class="border-ligne grid grid-cols-2 gap-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="reference">{{
          t('purchasing.orderForm.reference')
        }}</label>
        <input
          id="reference"
          v-model="form.reference"
          disabled
          autocomplete="off"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-sable px-3.5 text-texte-2"
        />
        <p class="text-texte-3 text-xs">{{ t('purchasing.orderForm.referenceGenerated') }}</p>
        <p v-if="fieldErrors.reference" class="text-critique text-xs">
          {{ fieldErrors.reference }}
        </p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="status">{{
          t('purchasing.orderForm.status')
        }}</label>
        <select
          id="status"
          v-model="form.status"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option value="DRAFT">{{ t('supplierOrderStatus.DRAFT') }}</option>
          <option value="CONFIRMED">{{ t('supplierOrderStatus.CONFIRMED') }}</option>
          <option value="CANCELLED">{{ t('supplierOrderStatus.CANCELLED') }}</option>
        </select>
        <p v-if="fieldErrors.status" class="text-critique text-xs">{{ fieldErrors.status }}</p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="supplier">{{
          t('purchasing.orderForm.supplier')
        }}</label>
        <select
          id="supplier"
          v-model="form.supplier"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option value="" disabled>{{ t('purchasing.orderForm.selectSupplier') }}</option>
          <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <p v-if="fieldErrors.supplier" class="text-critique text-xs">{{ fieldErrors.supplier }}</p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="product">{{
          t('purchasing.orderForm.product')
        }}</label>
        <select
          id="product"
          v-model="form.product"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option value="" disabled>{{ t('purchasing.orderForm.selectProduct') }}</option>
          <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <p v-if="fieldErrors.product" class="text-critique text-xs">{{ fieldErrors.product }}</p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="purchase_date">{{
          t('purchasing.orderForm.purchaseDate')
        }}</label>
        <input
          id="purchase_date"
          v-model="form.purchase_date"
          type="date"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p v-if="fieldErrors.purchase_date" class="text-critique text-xs">
          {{ fieldErrors.purchase_date }}
        </p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="currency">{{
          t('purchasing.orderForm.currency')
        }}</label>
        <select
          id="currency"
          v-model="form.currency"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option value="XOF">XOF</option>
        </select>
        <p v-if="fieldErrors.currency" class="text-critique text-xs">{{ fieldErrors.currency }}</p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="quantity_litres">{{
          t('purchasing.orderForm.quantity')
        }}</label>
        <input
          id="quantity_litres"
          v-model="form.quantity_litres"
          type="number"
          step="0.01"
          min="0.01"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p v-if="fieldErrors.quantity_litres" class="text-critique text-xs">
          {{ fieldErrors.quantity_litres }}
        </p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="unit_price">{{
          t('purchasing.orderForm.unitPrice')
        }}</label>
        <input
          id="unit_price"
          v-model="form.unit_price"
          type="number"
          step="0.0001"
          min="0"
          required
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p v-if="fieldErrors.unit_price" class="text-critique text-xs">
          {{ fieldErrors.unit_price }}
        </p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="optional_costs">{{
          t('purchasing.orderForm.optionalCosts')
        }}</label>
        <input
          id="optional_costs"
          v-model="form.optional_costs"
          type="number"
          step="0.01"
          min="0"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p v-if="fieldErrors.optional_costs" class="text-critique text-xs">
          {{ fieldErrors.optional_costs }}
        </p>
      </div>

      <div v-if="order" class="space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{
          t('purchasing.orderForm.totalAmount')
        }}</span>
        <p
          class="text-texte rounded-lg border border-transparent px-3.5 py-2.5 text-sm font-semibold"
        >
          {{ Number(order.total_amount).toLocaleString() }} {{ order.currency }}
        </p>
      </div>

      <div v-if="order" class="space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">{{
          t('purchasing.orderForm.reliquat')
        }}</span>
        <p
          class="rounded-lg border border-transparent px-3.5 py-2.5 text-sm font-semibold"
          :class="Number(order.reliquat) <= 0 ? 'text-critique' : 'text-livre-texte'"
        >
          {{ Number(order.reliquat).toLocaleString() }} L
        </p>
      </div>

      <div class="col-span-2 space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="notes">{{
          t('purchasing.orderForm.notes')
        }}</label>
        <textarea
          id="notes"
          v-model="form.notes"
          rows="2"
          class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p v-if="fieldErrors.notes" class="text-critique text-xs">{{ fieldErrors.notes }}</p>
      </div>

      <div class="col-span-2 flex justify-end gap-2 pt-2">
        <Button variant="ghost" type="button" @click="router.push({ name: 'supplier-orders' })">
          {{ t('purchasing.orderForm.back') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('purchasing.orderForm.saving') : t('purchasing.orderForm.save') }}
        </Button>
      </div>
    </form>

    <section v-if="!isNew" class="border-ligne space-y-3 rounded-xl border bg-surface p-6">
      <h2 class="font-display text-lg leading-none font-semibold uppercase">
        {{ t('purchasing.orderForm.documents') }}
      </h2>
      <p v-if="uploadError" class="text-critique text-sm">{{ uploadError }}</p>

      <ul class="space-y-1">
        <li v-for="doc in order?.documents ?? []" :key="doc.id" class="text-sm">
          <a :href="doc.file" target="_blank" class="text-texte underline hover:text-texte-2">
            {{ doc.reference || doc.document_type }}
          </a>
          <span class="text-texte-3"> — {{ doc.document_type }}</span>
        </li>
        <li v-if="!order?.documents?.length" class="text-texte-3 text-sm">
          {{ t('purchasing.orderForm.noDocuments') }}
        </li>
      </ul>

      <div class="flex flex-wrap items-center gap-2 pt-2">
        <select
          v-model="documentType"
          class="border-ligne-forte h-12 rounded-lg border bg-white px-3.5 text-sm focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option value="purchase_contract">
            {{ t('purchasing.orderForm.documentTypes.purchase_contract') }}
          </option>
          <option value="receipt">{{ t('purchasing.orderForm.documentTypes.receipt') }}</option>
          <option value="other">{{ t('purchasing.orderForm.documentTypes.other') }}</option>
        </select>
        <input
          type="file"
          accept="application/pdf,image/*"
          class="text-texte-2 text-sm"
          @change="onFileChange"
        />
        <Button
          type="button"
          variant="primary"
          :disabled="!documentFile || uploadingDoc"
          @click="onUploadDocument"
        >
          {{
            uploadingDoc ? t('purchasing.orderForm.uploading') : t('purchasing.orderForm.upload')
          }}
        </Button>
      </div>
    </section>

    <section v-if="!isNew" class="border-ligne space-y-3 rounded-xl border bg-surface p-6">
      <div class="flex items-center justify-between">
        <h2 class="font-display text-lg leading-none font-semibold uppercase">
          {{ t('purchasing.orderForm.cessionLetters') }}
        </h2>
        <Button variant="primary" @click="goToNewCession">
          {{ t('purchasing.orderForm.newCession') }}
        </Button>
      </div>

      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-2 py-1.5 font-medium">{{ t('purchasing.orderForm.table.reference') }}</th>
            <th class="px-2 py-1.5 font-medium text-right">
              {{ t('purchasing.orderForm.table.authorized') }}
            </th>
            <th class="px-2 py-1.5 font-medium text-right">
              {{ t('purchasing.orderForm.table.remaining') }}
            </th>
            <th class="px-2 py-1.5 font-medium">{{ t('purchasing.orderForm.table.status') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="cession in order?.cessions ?? []"
            :key="cession.id"
            class="border-ligne border-b last:border-0"
          >
            <td class="px-2 py-1.5">{{ cession.reference }}</td>
            <td class="px-2 py-1.5 text-right">
              {{ Number(cession.authorized_quantity).toLocaleString() }}
            </td>
            <td class="px-2 py-1.5 text-right">
              {{ Number(cession.remaining_quantity).toLocaleString() }}
            </td>
            <td class="px-2 py-1.5">{{ t(`cessionStatus.${cession.status}`) }}</td>
          </tr>
          <tr v-if="!order?.cessions?.length">
            <td colspan="4" class="text-texte-3 px-2 py-4 text-center">
              {{ t('purchasing.orderForm.noCessions') }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
