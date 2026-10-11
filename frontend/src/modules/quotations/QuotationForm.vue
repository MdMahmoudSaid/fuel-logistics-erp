<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// AZUR ÉNERGIE product decision 2026-09-05: quotation ("Offre commerciale")
// create/edit form - existing customer optional, free temporary customer
// name allowed, repeatable product/description/quantity/unit/unit price
// lines, validity date, notes/terms. Standalone: never touches Sale/
// Invoice/stock/treasury (see backend/apps/quotations/models.py).
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { createResourceApi } from '@/api/resource'
import { translateApiError, extractFieldErrors } from '@/i18n/apiErrors'
import { formatMoney } from '@/utils/currency'
import { quotationResource, duplicateQuotation, exportQuotationPdf } from './api'
import { printDocumentPdf } from '@/modules/documents/api'
import { QUOTATION_STATUSES } from './types'
import type { Quotation, QuotationLineInput, QuotationStatus } from './types'
import type { CustomerBrief, ProductBrief } from '@/modules/sales/types'
import AppLogo from '@/components/AppLogo.vue'
import Button from '@/components/ui/Button.vue'
import SearchableSelect from '@/components/ui/SearchableSelect.vue'
import MonoValue from '@/components/ui/MonoValue.vue'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()

const quotationId = computed(() => (route.params.id ? Number(route.params.id) : null))
const isNew = computed(() => quotationId.value === null)

const customers = ref<CustomerBrief[]>([])
const products = ref<ProductBrief[]>([])
const quotation = ref<Quotation | null>(null)

function emptyLine(): QuotationLineInput {
  return { product: null, description: '', quantity: '', unit: '', unit_price: '' }
}

const form = ref({
  customer: '',
  customer_name: '',
  status: 'DRAFT' as QuotationStatus,
  issue_date: new Date().toISOString().slice(0, 10),
  validity_date: '',
  notes: '',
  payment_terms: '',
  show_bank_accounts: true,
  lines: [emptyLine()] as QuotationLineInput[],
})

const saving = ref(false)
const duplicating = ref(false)
const exporting = ref(false)
const error = ref('')
const fieldErrors = ref<Record<string, string>>({})

const customerResource = createResourceApi<CustomerBrief>('/customers/')
const productResource = createResourceApi<ProductBrief>('/products/')

const customerOptions = computed(() => [
  { value: '', label: t('quotations.form.noExistingCustomer') },
  ...customers.value.map((c) => ({ value: String(c.id), label: c.name })),
])

async function loadQuotation() {
  if (quotationId.value === null) return
  quotation.value = await quotationResource.get!(quotationId.value)
  form.value = {
    customer: quotation.value.customer ? String(quotation.value.customer) : '',
    customer_name: quotation.value.customer_name,
    status: quotation.value.status,
    issue_date: quotation.value.issue_date,
    validity_date: quotation.value.validity_date ?? '',
    notes: quotation.value.notes,
    payment_terms: quotation.value.payment_terms ?? '',
    show_bank_accounts: quotation.value.show_bank_accounts ?? true,
    lines: quotation.value.lines.map((l) => ({
      product: l.product,
      description: l.description,
      quantity: l.quantity,
      unit: l.unit,
      unit_price: l.unit_price,
    })),
  }
}

onMounted(async () => {
  const [customerData, productData] = await Promise.all([
    customerResource.list(),
    productResource.list(),
  ])
  customers.value = customerData.results
  products.value = productData.results
  await loadQuotation()
})

function addLine() {
  form.value.lines = [...form.value.lines, emptyLine()]
}

function removeLine(index: number) {
  if (form.value.lines.length <= 1) return
  form.value.lines = form.value.lines.filter((_, i) => i !== index)
}

function lineTotal(line: QuotationLineInput): number {
  const qty = Number(line.quantity)
  const price = Number(line.unit_price)
  if (!Number.isFinite(qty) || !Number.isFinite(price)) return 0
  return qty * price
}

const computedTotal = computed(() =>
  form.value.lines.reduce((sum, line) => sum + lineTotal(line), 0),
)

async function onSubmit() {
  saving.value = true
  error.value = ''
  fieldErrors.value = {}
  const payload: Record<string, unknown> = {
    customer: form.value.customer ? Number(form.value.customer) : null,
    customer_name: form.value.customer_name,
    issue_date: form.value.issue_date,
    validity_date: form.value.validity_date || null,
    notes: form.value.notes,
    payment_terms: form.value.payment_terms,
    show_bank_accounts: form.value.show_bank_accounts,
    lines: form.value.lines.map((line) => ({
      product: line.product,
      description: line.description,
      // DRF DecimalField expects a string (never a float) to preserve
      // exact precision - matches the app-wide convention (see types.ts).
      // Explicit String(...) here rather than trusting the <input
      // type="number"> DOM value's type, which is not guaranteed by
      // v-model alone without the .number modifier.
      quantity: String(line.quantity),
      unit: line.unit,
      unit_price: String(line.unit_price),
    })),
  }
  if (!isNew.value) payload.status = form.value.status

  try {
    if (isNew.value) {
      const created = await quotationResource.create(payload)
      // Same form instance on the detail route: PDF / Print need it now.
      quotation.value = created
      router.replace({ name: 'quotation-detail', params: { id: created.id } })
    } else {
      quotation.value = await quotationResource.update(quotationId.value!, payload)
      form.value.status = quotation.value.status
    }
  } catch (e) {
    const response = (e as { response?: { status?: number; data?: Record<string, unknown> } })
      ?.response
    const body = response?.status === 400 ? response.data : undefined
    fieldErrors.value = extractFieldErrors(body)
    const generic = body?.detail ?? body?.non_field_errors
    const genericMessage = Array.isArray(generic) ? generic[0] : generic
    error.value =
      translateApiError(typeof genericMessage === 'string' ? genericMessage : undefined) ??
      (Object.values(fieldErrors.value).join('\n') || t('quotations.form.saveError'))
  } finally {
    saving.value = false
  }
}

async function onDuplicate() {
  if (quotationId.value === null) return
  duplicating.value = true
  try {
    const copy = await duplicateQuotation(quotationId.value)
    router.push({ name: 'quotation-detail', params: { id: copy.id } })
  } catch {
    error.value = t('quotations.list.duplicateError')
  } finally {
    duplicating.value = false
  }
}

async function onExportPdf() {
  if (!quotation.value) return
  exporting.value = true
  try {
    await exportQuotationPdf(quotation.value.id, quotation.value.reference, locale.value)
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exporting.value = false
  }
}

// Prints the designed proforma PDF, not the edit form.
async function printQuotation() {
  if (!quotation.value) return
  try {
    await printDocumentPdf('/quotations/', quotation.value.id, locale.value)
  } catch {
    error.value = t('reports.exportError')
  }
}
</script>

<template>
  <div class="max-w-3xl space-y-6">
    <!-- Print-only branding + hidden action buttons (client feedback
    2026-09-06): window.print() on this page printed the raw edit form
    together with its Imprimer/Exporter/Dupliquer/Retour/Enregistrer
    buttons and had no logo/company name - see SupplierLedgerView.vue for
    the full rationale. The form fields themselves stay exactly as-is
    when printed (the client wants "toutes les donnees comme il" - only
    the buttons are UI, not data). -->
    <div class="hidden items-center gap-2.5 print:mb-2 print:flex">
      <AppLogo :size="36" />
    </div>
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{
          isNew
            ? t('quotations.form.newTitle')
            : t('quotations.form.editTitle', { reference: quotation?.reference ?? '' })
        }}
      </h1>
      <div v-if="!isNew" class="no-print flex flex-wrap gap-2">
        <Button variant="ghost" type="button" @click="printQuotation">
          {{ t('reports.print') }}
        </Button>
        <Button variant="ghost" type="button" :disabled="exporting" @click="onExportPdf">
          {{ t('reports.exportPdf') }}
        </Button>
        <Button variant="ghost" type="button" :disabled="duplicating" @click="onDuplicate">
          {{ t('quotations.list.duplicate') }}
        </Button>
      </div>
    </div>

    <AppAlert v-if="error" :message="error" />

    <form
      class="border-ligne grid grid-cols-1 gap-4 rounded-xl border bg-surface p-6 md:grid-cols-2"
      @submit.prevent="onSubmit"
    >
      <div class="space-y-1.5">
        <span class="text-texte-2 text-sm font-medium">
          {{ t('quotations.form.customer') }}
        </span>
        <SearchableSelect
          v-model="form.customer"
          :options="customerOptions"
          :placeholder="t('quotations.form.selectCustomer')"
        />
        <p v-if="fieldErrors.customer" class="text-critique text-xs">{{ fieldErrors.customer }}</p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="customer_name">
          {{ t('quotations.form.customerName') }}
        </label>
        <input
          id="customer_name"
          v-model="form.customer_name"
          type="text"
          :placeholder="t('quotations.form.customerNamePlaceholder')"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p v-if="fieldErrors.customer_name" class="text-critique text-xs">
          {{ fieldErrors.customer_name }}
        </p>
      </div>

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="issue_date">
          {{ t('quotations.form.issueDate') }}
        </label>
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

      <div class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="validity_date">
          {{ t('quotations.form.validityDate') }}
        </label>
        <input
          id="validity_date"
          v-model="form.validity_date"
          type="date"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p v-if="fieldErrors.validity_date" class="text-critique text-xs">
          {{ fieldErrors.validity_date }}
        </p>
      </div>

      <div v-if="!isNew" class="space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="status">
          {{ t('quotations.form.status') }}
        </label>
        <select
          id="status"
          v-model="form.status"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <option v-for="s in QUOTATION_STATUSES" :key="s" :value="s">
            {{ t(`quotationStatus.${s}`) }}
          </option>
        </select>
        <p v-if="fieldErrors.status" class="text-critique text-xs">{{ fieldErrors.status }}</p>
      </div>

      <div class="col-span-full space-y-2">
        <div class="flex items-center justify-between">
          <h2 class="font-display text-sm font-semibold uppercase">
            {{ t('quotations.form.lines') }}
          </h2>
          <Button variant="ghost" type="button" size="md" class="no-print" @click="addLine">
            {{ t('quotations.form.addLine') }}
          </Button>
        </div>

        <div
          v-for="(line, index) in form.lines"
          :key="index"
          data-test="quotation-line"
          class="border-ligne grid grid-cols-1 gap-2 rounded-lg border p-3 sm:grid-cols-6"
        >
          <select
            v-model="line.product"
            class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm sm:col-span-2"
          >
            <option :value="null">{{ t('quotations.form.noProduct') }}</option>
            <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <input
            v-model="line.description"
            type="text"
            :placeholder="t('quotations.form.description')"
            class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm sm:col-span-2"
          />
          <input
            v-model="line.quantity"
            type="number"
            step="0.01"
            min="0.01"
            required
            :placeholder="t('quotations.form.quantity')"
            class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
          />
          <input
            v-model="line.unit"
            type="text"
            :placeholder="t('quotations.form.unit')"
            class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
          />
          <input
            v-model="line.unit_price"
            type="number"
            step="0.0001"
            min="0"
            required
            :placeholder="t('quotations.form.unitPrice')"
            class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
          />
          <div class="flex items-center justify-between sm:col-span-6">
            <MonoValue :value="formatMoney(lineTotal(line))" align="left" />
            <button
              type="button"
              data-test="quotation-line-remove"
              class="no-print text-critique text-sm underline disabled:opacity-30"
              :disabled="form.lines.length <= 1"
              @click="removeLine(index)"
            >
              {{ t('common.delete') }}
            </button>
          </div>
        </div>
        <p v-if="fieldErrors.lines" class="text-critique text-xs">{{ fieldErrors.lines }}</p>

        <div class="flex justify-end pt-1 text-sm">
          <span class="text-texte-2 font-medium">{{ t('quotations.form.total') }}&nbsp;</span>
          <MonoValue :value="formatMoney(computedTotal)" align="left" class="font-semibold" />
        </div>
      </div>

      <div class="col-span-full space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="payment_terms">
          {{ t('quotations.form.paymentTerms') }}
        </label>
        <input
          id="payment_terms"
          v-model="form.payment_terms"
          type="text"
          :placeholder="t('quotations.form.paymentTermsPlaceholder')"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <label class="text-texte-2 flex items-center gap-2 pt-1 text-sm">
          <input id="show_bank_accounts" v-model="form.show_bank_accounts" type="checkbox" />
          {{ t('quotations.form.showBankAccounts') }}
        </label>
      </div>

      <div class="col-span-full space-y-1.5">
        <label class="text-texte-2 text-sm font-medium" for="notes">
          {{ t('quotations.form.notes') }}
        </label>
        <textarea
          id="notes"
          v-model="form.notes"
          rows="3"
          class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
        <p v-if="fieldErrors.notes" class="text-critique text-xs">{{ fieldErrors.notes }}</p>
      </div>

      <div class="no-print col-span-full flex justify-end gap-2 pt-2">
        <Button variant="ghost" type="button" @click="router.push({ name: 'proformas' })">
          {{ t('quotations.form.back') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('quotations.form.saving') : t('quotations.form.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>
