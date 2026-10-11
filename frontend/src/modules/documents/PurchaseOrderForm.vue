<script setup lang="ts">
// Purchase order to a supplier (spec 2026-10-11 documents-commerciaux §6):
// products, quantities and prices, optionally pre-filled from a supplier
// order.
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import AppAlert from '@/components/ui/AppAlert.vue'
import Button from '@/components/ui/Button.vue'
import { formatMoney } from '@/utils/currency'
import DocumentFormHeader from './DocumentFormHeader.vue'
import LinesTable from './LinesTable.vue'
import { listAll } from './api'
import type { LineColumn } from './LinesTable.vue'
import type { PurchaseOrderDocument, PurchaseOrderLine } from './types'
import { CARD_CLASS, FIELD_CLASS, LABEL_CLASS, today, useDocumentForm } from './useDocumentForm'

interface SupplierOrderOption {
  id: number
  reference: string
  supplier: number
  product: number
  product_detail: { name: string } | null
  quantity_litres: string
  unit_price: string
  currency: string
}

const { t } = useI18n()
const { documentId, current, saving, busy, error, load, save, pdf, print, back } =
  useDocumentForm<PurchaseOrderDocument>('purchase')

const suppliers = ref<{ id: number; name: string }[]>([])
const supplierOrders = ref<SupplierOrderOption[]>([])
const form = ref({
  supplier: '',
  supplier_order: '',
  date: today(),
  delivery_place: '',
  delivery_date: '',
  payment_terms: '',
  currency: 'XOF',
  status: 'DRAFT' as PurchaseOrderDocument['status'],
  notes: '',
  lines: [] as Record<string, unknown>[],
})

const COLUMNS: LineColumn[] = [
  { field: 'description', labelKey: 'documents.lines.description' },
  { field: 'quantity', labelKey: 'documents.lines.quantity', type: 'number' },
  { field: 'unit', labelKey: 'documents.lines.unit' },
  { field: 'unit_price', labelKey: 'documents.lines.unitPrice', type: 'number', step: '0.0001' },
]
const newLine = (): Record<string, unknown> => ({
  product: null,
  description: '',
  quantity: '',
  unit: 'L',
  unit_price: '',
})

const title = computed(() =>
  current.value
    ? t('documents.purchase.edit', { reference: current.value.reference })
    : t('documents.purchase.new'),
)
const total = computed(() =>
  form.value.lines.reduce(
    (sum, line) => sum + (Number(line.quantity) || 0) * (Number(line.unit_price) || 0),
    0,
  ),
)

function onPrefill() {
  const order = supplierOrders.value.find((o) => String(o.id) === form.value.supplier_order)
  if (!order) return
  form.value.supplier = String(order.supplier)
  form.value.currency = order.currency
  form.value.lines = [
    {
      product: order.product,
      description: order.product_detail?.name ?? '',
      quantity: order.quantity_litres,
      unit: 'L',
      unit_price: order.unit_price,
    },
  ]
}

onMounted(async () => {
  try {
    const [allSuppliers, allOrders, order] = await Promise.all([
      listAll(createResourceApi<{ id: number; name: string }>('/suppliers/')),
      listAll(createResourceApi<SupplierOrderOption>('/supplier-orders/')),
      load(),
    ])
    suppliers.value = allSuppliers
    supplierOrders.value = allOrders
    if (order) {
      form.value = {
        supplier: order.supplier ? String(order.supplier) : '',
        supplier_order: order.supplier_order ? String(order.supplier_order) : '',
        date: order.date,
        delivery_place: order.delivery_place,
        delivery_date: order.delivery_date ?? '',
        payment_terms: order.payment_terms,
        currency: order.currency,
        status: order.status,
        notes: order.notes,
        lines: order.lines.map((line) => ({ ...line })),
      }
    } else {
      form.value.lines = [newLine()]
    }
  } catch {
    error.value = t('documents.common.loadError')
  }
})

function onSubmit() {
  const lines = form.value.lines.map((line) => ({
    product: line.product ?? null,
    description: line.description ?? '',
    quantity: line.quantity,
    unit: line.unit ?? '',
    unit_price: line.unit_price,
  })) as PurchaseOrderLine[]
  return save({
    supplier: form.value.supplier ? Number(form.value.supplier) : null,
    supplier_order: form.value.supplier_order ? Number(form.value.supplier_order) : null,
    date: form.value.date,
    delivery_place: form.value.delivery_place,
    delivery_date: form.value.delivery_date || null,
    payment_terms: form.value.payment_terms,
    currency: form.value.currency,
    status: form.value.status,
    notes: form.value.notes,
    lines,
  })
}
</script>

<template>
  <div class="max-w-5xl space-y-5">
    <DocumentFormHeader
      :title="title"
      :saved="!!documentId"
      :busy="busy"
      @pdf="pdf"
      @print="print"
      @back="back"
    />
    <AppAlert v-if="error" :message="error" />

    <form class="space-y-5" @submit.prevent="onSubmit">
      <section :class="CARD_CLASS" class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5 sm:col-span-2">
          <span :class="LABEL_CLASS">{{ t('documents.purchase.prefill') }}</span>
          <select
            v-model="form.supplier_order"
            data-test="po-prefill"
            :class="FIELD_CLASS"
            @change="onPrefill"
          >
            <option value="">{{ t('documents.purchase.noPrefill') }}</option>
            <option v-for="o in supplierOrders" :key="o.id" :value="String(o.id)">
              {{ o.reference }} · {{ o.product_detail?.name }} · {{ o.quantity_litres }} L
            </option>
          </select>
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.purchase.supplier') }}</span>
          <select v-model="form.supplier" data-test="po-supplier" required :class="FIELD_CLASS">
            <option value="">{{ t('documents.purchase.selectSupplier') }}</option>
            <option v-for="s in suppliers" :key="s.id" :value="String(s.id)">{{ s.name }}</option>
          </select>
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.common.date') }}</span>
          <input v-model="form.date" type="date" required :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.purchase.deliveryPlace') }}</span>
          <input v-model="form.delivery_place" type="text" :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.purchase.deliveryDate') }}</span>
          <input v-model="form.delivery_date" type="date" :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.purchase.paymentTerms') }}</span>
          <input v-model="form.payment_terms" type="text" :class="FIELD_CLASS" />
        </label>
        <div class="grid grid-cols-2 gap-4">
          <label class="space-y-1.5">
            <span :class="LABEL_CLASS">{{ t('documents.purchase.currency') }}</span>
            <input v-model="form.currency" type="text" :class="FIELD_CLASS" />
          </label>
          <label class="space-y-1.5">
            <span :class="LABEL_CLASS">{{ t('documents.common.status') }}</span>
            <select v-model="form.status" :class="FIELD_CLASS">
              <option v-for="s in ['DRAFT', 'SENT']" :key="s" :value="s">
                {{ t(`documents.purchase.statuses.${s}`) }}
              </option>
            </select>
          </label>
        </div>
      </section>

      <section :class="CARD_CLASS">
        <h2 class="font-semibold">{{ t('documents.common.lines') }}</h2>
        <LinesTable v-model="form.lines" :columns="COLUMNS" :new-line="newLine" />
        <p class="text-end text-sm font-semibold" data-test="po-total">
          {{ t('documents.common.total') }} : {{ formatMoney(total) }}
        </p>
      </section>

      <section :class="CARD_CLASS">
        <label class="block space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.common.notes') }}</span>
          <textarea v-model="form.notes" rows="2" :class="FIELD_CLASS" class="h-auto py-2" />
        </label>
      </section>

      <div class="flex justify-end">
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('documents.common.saving') : t('documents.common.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>
