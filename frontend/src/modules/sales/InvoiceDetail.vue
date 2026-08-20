<script setup lang="ts">
// docs/PHASE_4_PLAN.md Etape 9. Once VALIDATED, the standard editable
// fields are hidden entirely and replaced by the audited correction form -
// InvoiceSerializer.validate() (backend/apps/sales/serializers.py) rejects
// a direct PATCH past that point anyway, but hiding the fields avoids the
// user hitting that rejection in the first place (guide Section 21).
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { invoiceResource, validateInvoice, correctInvoice } from './api'
import { translateApiError } from '@/i18n/apiErrors'
import { CORRECTABLE_INVOICE_FIELDS } from './types'
import type { Invoice } from './types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()

const invoiceId = computed(() => Number(route.params.id))

const invoice = ref<Invoice | null>(null)
const loading = ref(true)
const error = ref('')

const editForm = ref({ total_amount: '', issued_date: '' })

async function load() {
  loading.value = true
  error.value = ''
  try {
    invoice.value = await invoiceResource.get!(invoiceId.value)
    editForm.value = {
      total_amount: invoice.value.total_amount,
      issued_date: invoice.value.issued_date,
    }
  } catch {
    error.value = t('sales.invoiceDetail.loadError')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const isDraft = computed(() => invoice.value?.status === 'DRAFT')
const isValidated = computed(() => invoice.value?.status === 'VALIDATED')
const canValidate = computed(() => auth.can('sales', 'validate'))
const canEdit = computed(() => auth.can('sales', 'edit'))

const saving = ref(false)
const saveError = ref('')

async function onSaveDraft() {
  if (!invoice.value) return
  saving.value = true
  saveError.value = ''
  try {
    invoice.value = await invoiceResource.update(invoiceId.value, {
      total_amount: editForm.value.total_amount,
      issued_date: editForm.value.issued_date,
    })
  } catch {
    saveError.value = t('sales.invoiceDetail.saveError')
  } finally {
    saving.value = false
  }
}

const validating = ref(false)
const validateError = ref('')

async function onValidate() {
  validating.value = true
  validateError.value = ''
  try {
    invoice.value = await validateInvoice(invoiceId.value)
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    validateError.value = translateApiError(detail) || t('sales.invoiceDetail.validateError')
  } finally {
    validating.value = false
  }
}

// --- Correction workflow (only reachable once VALIDATED) ---
const showCorrectionForm = ref(false)
const correctionForm = ref({
  field: CORRECTABLE_INVOICE_FIELDS[0] as string,
  new_value: '',
  reason: '',
})
const correcting = ref(false)
const correctionError = ref('')

function openCorrectionForm() {
  showCorrectionForm.value = true
  correctionForm.value = { field: CORRECTABLE_INVOICE_FIELDS[0], new_value: '', reason: '' }
}

async function onSubmitCorrection() {
  correcting.value = true
  correctionError.value = ''
  try {
    invoice.value = await correctInvoice(
      invoiceId.value,
      correctionForm.value.field,
      correctionForm.value.new_value,
      correctionForm.value.reason,
    )
    showCorrectionForm.value = false
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    correctionError.value = translateApiError(detail) || t('sales.invoiceDetail.correctionError')
  } finally {
    correcting.value = false
  }
}

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-slate-100 text-slate-600',
  VALIDATED: 'bg-sky-100 text-sky-700',
  PARTIALLY_PAID: 'bg-amber-100 text-amber-700',
  PAID: 'bg-emerald-100 text-emerald-700',
  CANCELLED: 'bg-red-100 text-red-700',
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString()
}
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">
        {{ t('sales.invoiceDetail.title', { number: invoice?.invoice_number ?? '' }) }}
      </h2>
      <button class="px-3 py-2 text-sm text-slate-500" @click="router.push({ name: 'invoices' })">
        {{ t('sales.invoiceDetail.backToInvoices') }}
      </button>
    </div>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">{{ t('common.loading') }}</p>

    <template v-else-if="invoice">
      <section class="space-y-4 rounded border bg-white p-4 text-sm">
        <div class="flex items-center justify-between">
          <span
            class="rounded-full px-2 py-0.5 text-xs font-medium"
            :class="STATUS_BADGE[invoice.status]"
          >
            {{ t(`invoiceStatus.${invoice.status}`) }}
          </span>
          <button
            v-if="isDraft && canValidate"
            id="validate-invoice"
            type="button"
            :disabled="validating"
            class="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            @click="onValidate"
          >
            {{ validating ? t('sales.invoiceDetail.validating') : t('sales.invoiceDetail.validateInvoice') }}
          </button>
          <button
            v-else-if="isValidated && canEdit"
            id="correct-invoice"
            type="button"
            class="rounded border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700"
            @click="openCorrectionForm"
          >
            {{ t('sales.invoiceDetail.correctInvoice') }}
          </button>
        </div>
        <p v-if="validateError" class="text-sm text-red-600">{{ validateError }}</p>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <span class="text-slate-500">{{ t('sales.invoiceDetail.customer') }}</span>
            <p class="font-medium text-slate-800">
              <RouterLink
                v-if="invoice.sale_detail?.customer_detail"
                class="underline decoration-dotted"
                :to="{
                  name: 'customer-ledger',
                  params: { id: invoice.sale_detail.customer_detail.id },
                }"
              >
                {{ invoice.sale_detail.customer_detail.name }}
              </RouterLink>
            </p>
          </div>
          <div>
            <span class="text-slate-500">{{ t('sales.invoiceDetail.product') }}</span>
            <p class="font-medium text-slate-800">
              {{ invoice.sale_detail?.product_detail?.name }}
            </p>
          </div>
          <div>
            <span class="text-slate-500">{{ t('sales.invoiceDetail.deliveredQuantity') }}</span>
            <p class="font-medium text-slate-800">
              {{ Number(invoice.sale_detail?.delivered_quantity ?? 0).toLocaleString() }} L
            </p>
          </div>
          <div>
            <span class="text-slate-500">{{ t('sales.invoiceDetail.unitSellingPrice') }}</span>
            <p class="font-medium text-slate-800">
              {{ invoice.sale_detail?.unit_selling_price }} {{ invoice.sale_detail?.currency }}
            </p>
          </div>
          <div>
            <span class="text-slate-500">{{ t('sales.invoiceDetail.trip') }}</span>
            <RouterLink
              class="font-medium text-slate-800 underline decoration-dotted"
              :to="{ name: 'trip-detail', params: { id: invoice.sale_detail?.trip } }"
            >
              {{ invoice.sale_detail?.trip_reference }}
            </RouterLink>
          </div>
        </div>

        <template v-if="isDraft && canEdit">
          <p v-if="saveError" class="text-sm text-red-600">{{ saveError }}</p>
          <div class="grid grid-cols-2 gap-4">
            <div class="space-y-1">
              <label class="text-sm font-medium text-slate-600" for="total_amount">{{
                t('sales.invoiceDetail.totalAmount')
              }}</label>
              <input
                id="total_amount"
                v-model="editForm.total_amount"
                type="number"
                step="0.01"
                class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div class="space-y-1">
              <label class="text-sm font-medium text-slate-600" for="issued_date">{{
                t('sales.invoiceDetail.issuedDate')
              }}</label>
              <input
                id="issued_date"
                v-model="editForm.issued_date"
                type="date"
                class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div class="flex justify-end">
            <button
              type="button"
              :disabled="saving"
              class="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
              @click="onSaveDraft"
            >
              {{ saving ? t('sales.invoiceDetail.saving') : t('sales.invoiceDetail.save') }}
            </button>
          </div>
        </template>
        <div v-else class="text-base font-semibold text-slate-800">
          {{ t('sales.invoiceDetail.total') }} {{ Number(invoice.total_amount).toLocaleString() }}
          {{ invoice.sale_detail?.currency }}
          <span class="ml-2 text-sm font-normal text-slate-500"
            >{{ t('sales.invoiceDetail.issued') }} {{ invoice.issued_date }}</span
          >
        </div>
      </section>

      <section v-if="showCorrectionForm" class="space-y-3 rounded border bg-white p-4">
        <h3 class="text-base font-semibold text-slate-800">
          {{ t('sales.invoiceDetail.correctionTitle') }}
        </h3>
        <p class="text-sm text-slate-500">
          {{ t('sales.invoiceDetail.correctionHint') }}
        </p>
        <p v-if="correctionError" class="text-sm text-red-600">{{ correctionError }}</p>

        <form id="correction-form" class="space-y-3" @submit.prevent="onSubmitCorrection">
          <div class="space-y-1">
            <label class="text-sm font-medium text-slate-600" for="correction_field">{{
              t('sales.invoiceDetail.field')
            }}</label>
            <select
              id="correction_field"
              v-model="correctionForm.field"
              class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            >
              <option v-for="f in CORRECTABLE_INVOICE_FIELDS" :key="f" :value="f">{{ f }}</option>
            </select>
          </div>
          <div class="space-y-1">
            <label class="text-sm font-medium text-slate-600" for="correction_new_value">{{
              t('sales.invoiceDetail.newValue')
            }}</label>
            <input
              id="correction_new_value"
              v-model="correctionForm.new_value"
              required
              class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div class="space-y-1">
            <label class="text-sm font-medium text-slate-600" for="correction_reason">{{
              t('sales.invoiceDetail.reason')
            }}</label>
            <textarea
              id="correction_reason"
              v-model="correctionForm.reason"
              required
              rows="2"
              class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div class="flex justify-end gap-2">
            <button
              type="button"
              class="px-3 py-2 text-sm text-slate-500"
              @click="showCorrectionForm = false"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              type="submit"
              :disabled="correcting"
              class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {{
                correcting
                  ? t('sales.invoiceDetail.applying')
                  : t('sales.invoiceDetail.applyCorrection')
              }}
            </button>
          </div>
        </form>
      </section>

      <section class="space-y-3 rounded border bg-white p-4">
        <h3 class="text-base font-semibold text-slate-800">
          {{ t('sales.invoiceDetail.correctionAuditTrail') }}
        </h3>
        <ol class="space-y-3 border-l border-slate-200 pl-4">
          <li v-for="entry in invoice.corrections" :key="entry.id" class="relative text-sm">
            <span class="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-slate-400" />
            <p class="font-medium text-slate-800">
              {{ entry.field_name }}: {{ entry.previous_value }} → {{ entry.new_value }}
            </p>
            <p class="text-xs text-slate-500">
              {{ formatDateTime(entry.corrected_at) }} · {{ entry.corrected_by_detail?.email }}
            </p>
            <p class="text-slate-600">{{ entry.reason }}</p>
          </li>
          <li v-if="!invoice.corrections.length" class="text-slate-400">
            {{ t('sales.invoiceDetail.noCorrections') }}
          </li>
        </ol>
      </section>
    </template>
  </div>
</template>
