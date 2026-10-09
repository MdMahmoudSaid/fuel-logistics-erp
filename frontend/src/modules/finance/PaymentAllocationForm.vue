<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// docs/PHASE_5_PLAN.md Etape 10: customer selection, dynamic display of
// their unpaid invoices, and per-line allocation amounts - posted in one
// request to POST /api/customer-payments/ (backend/apps/finance/serializers.py
// CustomerPaymentSerializer consumes the nested `allocations` list via
// PaymentAllocationService.allocate_payment()).
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import { translateApiError } from '@/i18n/apiErrors'
import { createCustomerPaymentWithProof, fetchCustomerLedger } from './api'
import type {
  CustomerBrief,
  CustomerLedgerInvoice,
  CustomerPaymentDestination,
  InvoiceAllocationInput,
  PaymentMethod,
} from './types'
import Button from '@/components/ui/Button.vue'
import { formatMoney } from '@/utils/currency'
import { IMAGE_UPLOAD_ACCEPT, isAllowedImageFile } from '@/utils/imageUpload'

// Dedicated cash account name FinancePostingService owns server-side
// (backend/apps/finance/services.py FinancePostingService.VERS_MOI_ACCOUNT_NAME)
// - kept out of the plain cash-account picker below so a user can't pick it
// as an ordinary CASH destination (the backend would reject that: it's
// reserved for destination=VERS_MOI, which the server resolves on its own).
const VERS_MOI_ACCOUNT_NAME = 'Vers moi'

// advanceMode (client advances, 2026-10-09): the customer owes nothing, so
// the whole receipt is recorded as open credit - no invoice lines. The
// backend consumes it automatically when the customer's next invoice is
// validated (PaymentAllocationService.apply_customer_credit_to_invoice).
const props = defineProps<{ initialCustomerId?: number | null; advanceMode?: boolean }>()
const emit = defineEmits<{ success: [customerId: number]; cancel: [] }>()
const { t } = useI18n()

const customerResource = createResourceApi<CustomerBrief>('/customers/')
const customers = ref<CustomerBrief[]>([])
const unpaidInvoices = ref<CustomerLedgerInvoice[]>([])
const outstandingBalance = ref<string | null>(null)
const loadingInvoices = ref(false)

const form = ref({
  customer: '',
  amount: '',
  payment_date: new Date().toISOString().slice(0, 10),
  method: 'CASH' as PaymentMethod,
  destination: 'CASH' as CustomerPaymentDestination,
  bank_account: '',
  cash_account: '',
  reference: '',
  note: '',
})

const proofFile = ref<File | null>(null)
const proofError = ref('')

function onProofFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (file && !isAllowedImageFile(file)) {
    proofFile.value = null
    input.value = ''
    proofError.value = t('finance.payment.imageOnlyError')
    return
  }
  proofFile.value = file
  proofError.value = ''
}

const bankAccountResource = createResourceApi<{ id: number; name: string }>('/bank-accounts/')
const cashAccountResource = createResourceApi<{ id: number; name: string }>('/cash-accounts/')
const bankAccounts = ref<{ id: number; name: string }[]>([])
const cashAccounts = ref<{ id: number; name: string }[]>([])
// The "Vers moi" placeholder is never a valid choice for a plain CASH
// destination - it only ever gets attached server-side when destination is
// VERS_MOI (see the module-level comment above).
const selectableCashAccounts = computed(() =>
  cashAccounts.value.filter((a) => a.name !== VERS_MOI_ACCOUNT_NAME),
)

interface AllocationLine {
  invoice: string
  amount: string
}
const lines = ref<AllocationLine[]>([{ invoice: '', amount: '' }])
// Tracks whether the user has hand-edited a line since the last FIFO
// auto-fill - once true, changing the global amount no longer overwrites
// their edits (they can still force a fresh pass via the auto-allocate button).
const autoAllocateDirty = ref(false)

const saving = ref(false)
const error = ref('')

async function loadInvoices() {
  unpaidInvoices.value = []
  outstandingBalance.value = null
  if (!form.value.customer) return
  loadingInvoices.value = true
  try {
    const ledger = await fetchCustomerLedger(Number(form.value.customer))
    unpaidInvoices.value = ledger.invoices.filter(
      (inv) => Number(inv.outstanding) > 0 && inv.status !== 'CANCELLED' && inv.status !== 'DRAFT',
    )
    outstandingBalance.value = ledger.outstanding_balance
  } finally {
    loadingInvoices.value = false
  }
}

function runFifoAutoAllocate() {
  const amount = Number(form.value.amount)
  if (!amount || amount <= 0 || unpaidInvoices.value.length === 0) return

  const oldestFirst = [...unpaidInvoices.value].sort((a, b) =>
    a.issued_date === b.issued_date ? a.id - b.id : a.issued_date < b.issued_date ? -1 : 1,
  )

  let remaining = amount
  const newLines: AllocationLine[] = []
  for (const invoice of oldestFirst) {
    if (remaining <= 0) break
    const outstanding = Number(invoice.outstanding)
    if (outstanding <= 0) continue
    const allocated = Math.min(remaining, outstanding)
    newLines.push({ invoice: String(invoice.id), amount: allocated.toFixed(2) })
    remaining -= allocated
  }
  if (remaining > 0.001) {
    newLines.push({ invoice: '', amount: remaining.toFixed(2) })
  }

  lines.value = newLines.length > 0 ? newLines : [{ invoice: '', amount: '' }]
}

function autoAllocate() {
  autoAllocateDirty.value = false
  runFifoAutoAllocate()
}

function markLinesDirty() {
  autoAllocateDirty.value = true
}

watch(
  () => form.value.customer,
  async () => {
    autoAllocateDirty.value = false
    lines.value = [{ invoice: '', amount: '' }]
    await loadInvoices()
    runFifoAutoAllocate()
  },
)

watch(
  () => form.value.amount,
  () => {
    if (!autoAllocateDirty.value) runFifoAutoAllocate()
  },
)

onMounted(async () => {
  const [customerData, bankData, cashData] = await Promise.all([
    customerResource.list(),
    bankAccountResource.list(),
    cashAccountResource.list(),
  ])
  customers.value = customerData.results
  bankAccounts.value = bankData.results
  cashAccounts.value = cashData.results

  if (props.initialCustomerId) {
    form.value.customer = String(props.initialCustomerId)
    await loadInvoices()
  }
})

function addLine() {
  lines.value.push({ invoice: '', amount: '' })
  autoAllocateDirty.value = true
}

function removeLine(index: number) {
  lines.value.splice(index, 1)
  autoAllocateDirty.value = true
}

const allocatedTotal = computed(() =>
  lines.value.reduce((sum, line) => sum + (Number(line.amount) || 0), 0),
)
const unallocatedRemainder = computed(() => (Number(form.value.amount) || 0) - allocatedTotal.value)

async function onSubmit() {
  saving.value = true
  error.value = ''
  proofError.value = ''
  try {
    // Bug fix (found during 2026-09-06 manual recette): the proof/
    // justificatif was made optional on customer payments (client
    // decision, backend CustomerPaymentSerializer.validate_proof already
    // accepts None) - this form's own hard client-side gate was never
    // updated to match, silently blocking every customer payment that
    // had no proof file attached, with the "required" HTML attribute on
    // #proof_file (also removed) giving no visible error either since
    // that input is visually hidden (sr-only).

    const allocations: InvoiceAllocationInput[] = props.advanceMode
      ? [{ invoice: null, amount: String(form.value.amount) }]
      : lines.value
          .filter((line) => line.amount)
          .map((line) => ({
            invoice: line.invoice ? Number(line.invoice) : null,
            amount: line.amount,
          }))

    const payload: Record<string, unknown> = {
      customer: Number(form.value.customer),
      amount: form.value.amount,
      payment_date: form.value.payment_date,
      method: form.value.method,
      reference: form.value.reference,
      note: form.value.note,
      destination: form.value.destination,
      allocations,
    }
    // BANK/CASH need their matching account; VERS_MOI/INDIRECT are fully
    // resolved server-side (CustomerPaymentSerializer.validate() derives
    // is_indirect and the account to use from `destination` alone).
    if (form.value.destination === 'BANK') {
      payload.bank_account = Number(form.value.bank_account)
    } else if (form.value.destination === 'CASH') {
      payload.cash_account = Number(form.value.cash_account)
    }

    const created = await createCustomerPaymentWithProof(payload, proofFile.value)

    emit('success', Number(created.customer))
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = translateApiError(detail) || t('finance.payment.saveError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <AppAlert v-if="error" :message="error" />

    <form
      class="border-ligne space-y-4 rounded-xl border bg-surface p-6"
      @submit.prevent="onSubmit"
    >
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="customer">{{
            t('finance.payment.customer')
          }}</label>
          <select
            id="customer"
            v-model="form.customer"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.payment.selectCustomer') }}</option>
            <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="amount">{{
            t('finance.payment.amount')
          }}</label>
          <input
            id="amount"
            v-model="form.amount"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="payment_date">{{
            t('finance.payment.paymentDate')
          }}</label>
          <input
            id="payment_date"
            v-model="form.payment_date"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="method">{{
            t('finance.payment.method')
          }}</label>
          <select
            id="method"
            v-model="form.method"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="CASH">{{ t('paymentMethod.CASH') }}</option>
            <option value="BANK_TRANSFER">{{ t('paymentMethod.BANK_TRANSFER') }}</option>
            <option value="CHEQUE">{{ t('paymentMethod.CHEQUE') }}</option>
            <option value="OTHER">{{ t('paymentMethod.OTHER') }}</option>
          </select>
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="reference">{{
            t('finance.payment.reference')
          }}</label>
          <input
            id="reference"
            v-model="form.reference"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>

        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="destination">{{
            t('finance.payment.destination')
          }}</label>
          <select
            id="destination"
            v-model="form.destination"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="CASH">{{ t('finance.payment.cash') }}</option>
            <option value="BANK">{{ t('finance.payment.bank') }}</option>
            <option value="VERS_MOI">{{ t('finance.payment.destinationVersMoi') }}</option>
            <option value="INDIRECT">{{ t('finance.payment.destinationIndirect') }}</option>
          </select>
        </div>
      </div>

      <div
        v-if="form.destination === 'BANK' || form.destination === 'CASH'"
        class="border-ligne grid grid-cols-1 md:grid-cols-2 gap-4 border-t pt-4"
      >
        <div v-if="form.destination === 'BANK'" class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="bank_account">{{
            t('finance.payment.bankAccount')
          }}</label>
          <select
            id="bank_account"
            v-model="form.bank_account"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.payment.selectBankAccount') }}</option>
            <option v-for="a in bankAccounts" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </div>
        <div v-else class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="cash_account">{{
            t('finance.payment.cashAccount')
          }}</label>
          <select
            id="cash_account"
            v-model="form.cash_account"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.payment.selectCashAccount') }}</option>
            <option v-for="a in selectableCashAccounts" :key="a.id" :value="a.id">
              {{ a.name }}
            </option>
          </select>
        </div>
      </div>

      <div class="border-ligne space-y-1.5 border-t pt-4">
        <label class="text-texte-2 text-sm font-medium" for="note">{{
          t('finance.payment.note')
        }}</label>
        <textarea
          id="note"
          v-model="form.note"
          rows="2"
          class="border-ligne-forte w-full rounded-lg border bg-white px-3.5 py-2.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        />
      </div>

      <div class="border-ligne space-y-1.5 border-t pt-4">
        <label class="text-texte-2 text-sm font-medium" for="proof_file">{{
          t('finance.payment.proofLabel')
        }}</label>
        <div class="flex flex-wrap items-center gap-3">
          <label
            for="proof_file"
            class="border-ligne-forte text-texte hover:bg-sable inline-flex h-11 cursor-pointer items-center rounded-lg border bg-white px-3 text-sm font-medium transition"
          >
            {{ t('finance.payment.chooseFile') }}
          </label>
          <span class="text-texte-2 text-sm">
            {{ proofFile?.name || t('finance.payment.noFileSelected') }}
          </span>
        </div>
        <input
          id="proof_file"
          type="file"
          :accept="IMAGE_UPLOAD_ACCEPT"
          class="sr-only"
          @change="onProofFileChange"
        />
        <AppAlert v-if="proofError" :message="proofError" />
      </div>

      <p
        v-if="advanceMode"
        class="border-ligne text-texte-2 border-t pt-4 text-sm"
        data-test="advance-explanation"
      >
        {{ t('finance.customerLedger.advanceExplanation') }}
      </p>

      <div v-if="!advanceMode && outstandingBalance !== null" class="border-ligne border-t pt-4">
        <p class="text-texte-2 text-sm font-medium" data-test="outstanding-balance">
          {{ t('finance.payment.outstandingBalance') }}:
          <span class="text-texte font-semibold">{{ formatMoney(outstandingBalance ?? 0) }}</span>
        </p>
      </div>

      <div v-if="!advanceMode" class="border-ligne space-y-2 border-t pt-4">
        <div class="flex items-center justify-between">
          <h2 class="font-display text-sm font-semibold uppercase">
            {{ t('finance.payment.allocateToInvoices') }}
          </h2>
          <div class="flex items-center gap-3">
            <button
              type="button"
              data-test="auto-allocate"
              class="text-texte-2 hover:text-texte text-sm"
              @click="autoAllocate"
            >
              {{ t('finance.payment.autoAllocate') }}
            </button>
            <button type="button" class="text-texte-2 hover:text-texte text-sm" @click="addLine">
              {{ t('finance.payment.addLine') }}
            </button>
          </div>
        </div>
        <p v-if="loadingInvoices" class="text-texte-3 text-sm">
          {{ t('finance.payment.loadingInvoices') }}
        </p>

        <div v-for="(line, index) in lines" :key="index" class="flex items-center gap-2">
          <select
            v-model="line.invoice"
            data-test="line-invoice"
            class="border-ligne-forte h-12 flex-1 rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            @change="markLinesDirty"
          >
            <option value="">{{ t('finance.payment.unallocatedCredit') }}</option>
            <option v-for="inv in unpaidInvoices" :key="inv.id" :value="inv.id">
              {{ inv.invoice_number }} — {{ t('finance.payment.invoiceOptionRemaining') }}
              {{ formatMoney(inv.outstanding) }}
            </option>
          </select>
          <input
            v-model="line.amount"
            type="number"
            step="0.01"
            min="0"
            data-test="line-amount"
            :placeholder="t('finance.payment.amountPlaceholder')"
            class="border-ligne-forte h-12 w-40 rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            @input="markLinesDirty"
          />
          <button
            type="button"
            class="text-critique text-sm hover:brightness-90"
            @click="removeLine(index)"
          >
            {{ t('finance.payment.remove') }}
          </button>
        </div>

        <p class="text-texte-2 text-sm">
          {{ t('finance.payment.allocatedSummary', { allocated: formatMoney(allocatedTotal) }) }}
          <span :class="unallocatedRemainder < 0 ? 'text-critique font-medium' : ''">
            {{ formatMoney(unallocatedRemainder) }}
          </span>
        </p>
      </div>

      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('cancel')">
          {{ t('common.cancel') }}
        </Button>
        <Button type="submit" variant="primary" :loading="saving">
          {{
            saving
              ? t('finance.payment.saving')
              : advanceMode
                ? t('finance.customerLedger.recordAdvance')
                : t('finance.payment.record')
          }}
        </Button>
      </div>
    </form>
  </div>
</template>
