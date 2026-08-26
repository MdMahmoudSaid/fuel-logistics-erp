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
import { formatMoney, formatQuantity } from '@/utils/currency'
import { invoiceResource, validateInvoice, correctInvoice } from './api'
import { translateApiError } from '@/i18n/apiErrors'
import { CORRECTABLE_INVOICE_FIELDS } from './types'
import type { Invoice } from './types'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import MonoValue from '@/components/ui/MonoValue.vue'

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

function badgeVariant(status: string) {
  if (status === 'PAID') return 'livre' as const
  if (status === 'VALIDATED') return 'transit' as const
  if (status === 'PARTIALLY_PAID') return 'ecart' as const
  if (status === 'CANCELLED') return 'critique' as const
  return 'neutre' as const
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString()
}
</script>

<template>
  <div class="max-w-2xl space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('sales.invoiceDetail.title', { number: invoice?.invoice_number ?? '' }) }}
      </h1>
      <Button variant="ghost" @click="router.push({ name: 'invoices' })">
        {{ t('sales.invoiceDetail.backToInvoices') }}
      </Button>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else-if="invoice">
      <section class="border-ligne space-y-4 rounded-xl border bg-white p-4 text-sm">
        <div class="flex items-center justify-between">
          <Badge :variant="badgeVariant(invoice.status)">
            {{ t(`invoiceStatus.${invoice.status}`) }}
          </Badge>
          <Button
            v-if="isDraft && canValidate"
            id="validate-invoice"
            :disabled="validating"
            @click="onValidate"
          >
            {{
              validating
                ? t('sales.invoiceDetail.validating')
                : t('sales.invoiceDetail.validateInvoice')
            }}
          </Button>
          <Button
            v-else-if="isValidated && canEdit"
            id="correct-invoice"
            variant="ghost"
            @click="openCorrectionForm"
          >
            {{ t('sales.invoiceDetail.correctInvoice') }}
          </Button>
        </div>
        <p v-if="validateError" class="text-critique text-sm">{{ validateError }}</p>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <span class="text-texte-2">{{ t('sales.invoiceDetail.customer') }}</span>
            <p class="text-texte font-medium">
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
            <span class="text-texte-2">{{ t('sales.invoiceDetail.product') }}</span>
            <p class="text-texte font-medium">
              {{ invoice.sale_detail?.product_detail?.name }}
            </p>
          </div>
          <div>
            <span class="text-texte-2">{{ t('sales.invoiceDetail.deliveredQuantity') }}</span>
            <p>
              <MonoValue
                class="font-medium"
                align="left"
                :value="formatQuantity(invoice.sale_detail?.delivered_quantity ?? 0)"
              />
            </p>
          </div>
          <div>
            <span class="text-texte-2">{{ t('sales.invoiceDetail.unitSellingPrice') }}</span>
            <p>
              <MonoValue
                class="font-medium"
                align="left"
                :value="invoice.sale_detail?.unit_selling_price ?? ''"
                :unit="invoice.sale_detail?.currency"
              />
            </p>
          </div>
          <div>
            <span class="text-texte-2">{{ t('sales.invoiceDetail.trip') }}</span>
            <RouterLink
              class="text-texte font-medium underline decoration-dotted"
              :to="{ name: 'trip-detail', params: { id: invoice.sale_detail?.trip } }"
            >
              {{ invoice.sale_detail?.trip_reference }}
            </RouterLink>
          </div>
        </div>

        <template v-if="isDraft && canEdit">
          <p v-if="saveError" class="text-critique text-sm">{{ saveError }}</p>
          <div class="grid grid-cols-2 gap-4">
            <div class="space-y-1">
              <label class="text-texte-2 text-sm font-medium" for="total_amount">{{
                t('sales.invoiceDetail.totalAmount')
              }}</label>
              <input
                id="total_amount"
                v-model="editForm.total_amount"
                type="number"
                step="0.01"
                class="border-ligne-forte h-11 w-full rounded-lg border bg-white px-3 text-sm"
              />
            </div>
            <div class="space-y-1">
              <label class="text-texte-2 text-sm font-medium" for="issued_date">{{
                t('sales.invoiceDetail.issuedDate')
              }}</label>
              <input
                id="issued_date"
                v-model="editForm.issued_date"
                type="date"
                class="border-ligne-forte h-11 w-full rounded-lg border bg-white px-3 text-sm"
              />
            </div>
          </div>
          <div class="flex justify-end">
            <Button :disabled="saving" @click="onSaveDraft">
              {{ saving ? t('sales.invoiceDetail.saving') : t('sales.invoiceDetail.save') }}
            </Button>
          </div>
        </template>
        <div v-else class="text-texte text-base font-semibold">
          {{ t('sales.invoiceDetail.total') }} {{ formatMoney(invoice.total_amount) }}
          <span class="text-texte-2 ms-2 text-sm font-normal"
            >{{ t('sales.invoiceDetail.issued') }} {{ invoice.issued_date }}</span
          >
        </div>
      </section>

      <Card v-if="showCorrectionForm" :title="t('sales.invoiceDetail.correctionTitle')">
        <div class="space-y-3">
          <p class="text-texte-2 text-sm">
            {{ t('sales.invoiceDetail.correctionHint') }}
          </p>
          <p v-if="correctionError" class="text-critique text-sm">{{ correctionError }}</p>

          <form id="correction-form" class="space-y-3" @submit.prevent="onSubmitCorrection">
            <div class="space-y-1">
              <label class="text-texte-2 text-sm font-medium" for="correction_field">{{
                t('sales.invoiceDetail.field')
              }}</label>
              <select
                id="correction_field"
                v-model="correctionForm.field"
                class="border-ligne-forte h-11 w-full rounded-lg border bg-white px-3 text-sm"
              >
                <option v-for="f in CORRECTABLE_INVOICE_FIELDS" :key="f" :value="f">{{ f }}</option>
              </select>
            </div>
            <div class="space-y-1">
              <label class="text-texte-2 text-sm font-medium" for="correction_new_value">{{
                t('sales.invoiceDetail.newValue')
              }}</label>
              <input
                id="correction_new_value"
                v-model="correctionForm.new_value"
                required
                class="border-ligne-forte h-11 w-full rounded-lg border bg-white px-3 text-sm"
              />
            </div>
            <div class="space-y-1">
              <label class="text-texte-2 text-sm font-medium" for="correction_reason">{{
                t('sales.invoiceDetail.reason')
              }}</label>
              <textarea
                id="correction_reason"
                v-model="correctionForm.reason"
                required
                rows="2"
                class="border-ligne-forte w-full rounded-lg border bg-white px-3 py-2 text-sm"
              />
            </div>
            <div class="flex justify-end gap-2">
              <Button type="button" variant="ghost" @click="showCorrectionForm = false">
                {{ t('common.cancel') }}
              </Button>
              <Button type="submit" :disabled="correcting">
                {{
                  correcting
                    ? t('sales.invoiceDetail.applying')
                    : t('sales.invoiceDetail.applyCorrection')
                }}
              </Button>
            </div>
          </form>
        </div>
      </Card>

      <Card :title="t('sales.invoiceDetail.correctionAuditTrail')">
        <ol class="border-ligne space-y-3 border-l ps-4">
          <li v-for="entry in invoice.corrections" :key="entry.id" class="relative text-sm">
            <span class="bg-texte-3 absolute top-1 -start-[21px] h-2 w-2 rounded-full" />
            <p class="text-texte font-medium">
              {{ entry.field_name }}: {{ entry.previous_value }} → {{ entry.new_value }}
            </p>
            <p class="text-texte-2 text-xs">
              {{ formatDateTime(entry.corrected_at) }} · {{ entry.corrected_by_detail?.email }}
            </p>
            <p class="text-texte-2">{{ entry.reason }}</p>
          </li>
          <li v-if="!invoice.corrections.length" class="text-texte-3">
            {{ t('sales.invoiceDetail.noCorrections') }}
          </li>
        </ol>
      </Card>
    </template>
  </div>
</template>
