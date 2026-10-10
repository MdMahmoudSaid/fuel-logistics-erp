<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
// docs/PHASE_5_PLAN.md Etape 8/10: gross fees earned, loss deductions,
// advances consumed and what's already settled for one transporter
// (guide Section 1.5/8.6: "earned - deductions - advances - payments =
// transporter outstanding"), backed by GET /api/transporters/{id}/ledger/.
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { fetchTransporterLedger, exportLedgerPdf, exportTransportPaymentPdf } from './api'
import type { TransporterLedger } from './types'
import { formatMoney } from '@/utils/currency'
import AppLogo from '@/components/AppLogo.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import AdvanceForm from './AdvanceForm.vue'
import DebtPaymentForm from './DebtPaymentForm.vue'
import Modal from '@/components/ui/Modal.vue'
import MonoValue from '@/components/ui/MonoValue.vue'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()

const ledger = ref<TransporterLedger | null>(null)
const loading = ref(true)
const error = ref('')
const showPaymentModal = ref(false)
const showAdvanceForm = ref(false)
const previewUrl = ref<string | null>(null)
const exporting = ref(false)
const exportingPaymentId = ref<number | null>(null)

const transporterId = computed(() => Number(route.params.id))

async function load() {
  loading.value = true
  error.value = ''
  try {
    ledger.value = await fetchTransporterLedger(transporterId.value)
  } catch {
    error.value = t('finance.transporterLedger.loadError')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const lastOperation = computed(() => {
  const advance = ledger.value?.summary.last_advance ?? null
  const payment = ledger.value?.summary.last_payment ?? null
  if (advance && payment) {
    return advance.date >= payment.date
      ? { kind: 'advance' as const, amount: advance.amount }
      : { kind: 'payment' as const, amount: payment.amount }
  }
  if (advance) return { kind: 'advance' as const, amount: advance.amount }
  if (payment) return { kind: 'payment' as const, amount: payment.amount }
  return null
})

async function onPaymentSuccess() {
  showPaymentModal.value = false
  await load()
}

async function onAdvanceSaved() {
  showAdvanceForm.value = false
  await load()
}

function printLedger() {
  window.print()
}

async function exportPdf() {
  exporting.value = true
  try {
    await exportLedgerPdf('transporter', transporterId.value, locale.value)
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exporting.value = false
  }
}

async function exportSettlementPdf(paymentId: number) {
  exportingPaymentId.value = paymentId
  try {
    await exportTransportPaymentPdf(paymentId, locale.value)
  } catch {
    error.value = t('reports.exportError')
  } finally {
    exportingPaymentId.value = null
  }
}

function badgeVariant(status: string) {
  if (status === 'PAID') return 'livre' as const
  if (status === 'PARTIALLY_PAID') return 'ecart' as const
  if (status === 'PAYABLE' || status === 'DEDUCTION_APPLIED') return 'transit' as const
  return 'neutre' as const
}
</script>

<template>
  <div class="max-w-4xl space-y-6">
    <!-- Print-only branding + hidden action row, see SupplierLedgerView.vue
    for the full rationale (client feedback 2026-09-06). -->
    <div class="hidden items-center gap-2.5 print:mb-2 print:flex">
      <AppLogo :size="36" />
    </div>
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('finance.transporterLedger.title', { name: ledger?.transporter.name ?? '…' }) }}
      </h1>
      <div class="no-print flex flex-wrap gap-2">
        <Button
          v-if="ledger && Number(ledger.summary.net_balance) < 0"
          variant="primary"
          @click="showPaymentModal = true"
        >
          {{ t('finance.transporterLedger.newPayment') }}
        </Button>
        <Button
          v-if="ledger && Number(ledger.summary.net_balance) >= 0"
          variant="secondary"
          @click="showAdvanceForm = true"
        >
          {{ t('finance.advanceForm.title') }}
        </Button>
        <Button v-if="ledger" variant="ghost" @click="printLedger">
          {{ t('reports.print') }}
        </Button>
        <Button v-if="ledger" variant="ghost" :disabled="exporting" @click="exportPdf">
          {{ t('reports.exportPdf') }}
        </Button>
        <Button variant="ghost" @click="router.push({ name: 'transporters' })">
          {{ t('finance.transporterLedger.back') }}
        </Button>
      </div>
    </div>

    <AppAlert v-if="error" :message="error" />
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else-if="ledger">
      <section class="grid gap-3 md:grid-cols-4">
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.partyLedger.totalDue') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :value="formatMoney(ledger.summary.total_due)"
          />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.partyLedger.openAdvances') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :value="formatMoney(ledger.summary.open_advances)"
          />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.partyLedger.netBalance') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :class="Number(ledger.summary.net_balance) < 0 ? 'text-critique' : 'text-livre'"
            :value="formatMoney(ledger.summary.net_balance)"
          />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.partyLedger.lastMovement') }}
          </p>
          <p class="text-texte text-sm">
            <template v-if="lastOperation">
              {{ t(`finance.partyLedger.${lastOperation.kind}`) }}:
              {{ formatMoney(lastOperation.amount) }}
            </template>
            <template v-else>—</template>
          </p>
        </div>
      </section>

      <Card :title="t('finance.transporterLedger.trucks')">
        <ul class="divide-ligne divide-y text-sm">
          <li
            v-for="truck in ledger.trucks"
            :key="truck.id"
            class="flex items-center justify-between py-2"
          >
            <span class="text-texte font-medium">{{ truck.internal_id }}</span>
            <span class="text-texte-2">
              {{ truck.tractor_registration }} / {{ truck.tanker_registration }}
            </span>
          </li>
          <li v-if="ledger.trucks.length === 0" class="text-texte-3 py-2">
            {{ t('finance.transporterLedger.noTrucks') }}
          </li>
        </ul>
      </Card>

      <Card :title="t('finance.transporterLedger.settlementsByTrip')">
        <div class="overflow-x-auto">
          <table class="w-full text-start text-sm">
            <thead>
              <tr class="border-ligne text-texte-2 border-b">
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.transporterLedger.table.trip') }}
                </th>
                <th class="px-2 py-1.5 font-medium text-right">
                  {{ t('finance.transporterLedger.table.base') }}
                </th>
                <th class="px-2 py-1.5 font-medium text-right">
                  {{ t('finance.transporterLedger.table.deduction') }}
                </th>
                <th class="px-2 py-1.5 font-medium text-right">
                  {{ t('finance.transporterLedger.table.net') }}
                </th>
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.transporterLedger.table.status') }}
                </th>
                <th class="px-2 py-1.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="payment in ledger.payments"
                :key="payment.id"
                class="border-ligne border-b last:border-0"
              >
                <td class="text-texte px-2 py-1.5 font-medium">{{ payment.trip_reference }}</td>
                <td class="px-2 py-1.5 text-right">
                  <MonoValue :value="formatMoney(payment.base_amount)" />
                </td>
                <td class="px-2 py-1.5 text-right text-red-600">
                  <MonoValue
                    class="text-critique"
                    :value="'− ' + formatMoney(payment.deduction_amount)"
                  />
                  <p v-if="payment.deduction_label" class="text-texte-3 mt-1 text-xs">
                    {{ payment.deduction_label }}
                  </p>
                </td>
                <td class="text-texte px-2 py-1.5 text-right font-medium">
                  <MonoValue :value="formatMoney(payment.net_amount)" />
                </td>
                <td class="px-2 py-1.5">
                  <Badge :variant="badgeVariant(payment.status)">
                    {{ t(`settlementStatus.${payment.status}`) }}
                  </Badge>
                </td>
                <td class="px-2 py-1.5 text-right">
                  <button
                    type="button"
                    data-test="settlement-pdf"
                    class="text-bitume underline disabled:opacity-50"
                    :disabled="exportingPaymentId === payment.id"
                    @click="exportSettlementPdf(payment.id)"
                  >
                    {{ t('finance.partyLedger.pdf') }}
                  </button>
                </td>
              </tr>
              <tr v-if="ledger.payments.length === 0">
                <td colspan="6" class="text-texte-3 px-2 py-4 text-center">
                  {{ t('finance.transporterLedger.noSettlements') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card :title="t('finance.transporterLedger.advances')">
        <div class="overflow-x-auto">
          <table class="w-full text-start text-sm">
            <thead>
              <tr class="border-ligne text-texte-2 border-b">
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.transporterLedger.advancesTable.date') }}
                </th>
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.transporterLedger.advancesTable.reference') }}
                </th>
                <th class="px-2 py-1.5 font-medium">
                  {{ t('finance.transporterLedger.advancesTable.settled') }}
                </th>
                <th class="px-2 py-1.5 font-medium text-right">
                  {{ t('finance.transporterLedger.advancesTable.amount') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="advance in ledger.advances"
                :key="advance.id"
                class="border-ligne border-b last:border-0"
              >
                <td class="px-2 py-1.5">{{ advance.date }}</td>
                <td class="px-2 py-1.5">{{ advance.reference || '—' }}</td>
                <td class="px-2 py-1.5">{{ advance.settled ? t('common.yes') : t('common.no') }}</td>
                <td class="text-texte px-2 py-1.5 text-right font-medium">
                  <MonoValue :value="formatMoney(advance.amount)" />
                </td>
              </tr>
              <tr v-if="ledger.advances.length === 0">
                <td colspan="4" class="text-texte-3 px-2 py-4 text-center">
                  {{ t('finance.transporterLedger.noAdvances') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card :title="t('finance.partyLedger.entriesTitle')">
        <div class="overflow-x-auto">
          <table class="w-full text-start text-sm">
            <thead>
              <tr class="border-ligne text-texte-2 border-b">
                <th class="px-3 py-2.5 font-medium">{{ t('finance.partyLedger.table.date') }}</th>
                <th class="px-3 py-2.5 font-medium">{{ t('finance.partyLedger.table.type') }}</th>
                <th class="px-3 py-2.5 font-medium">
                  {{ t('finance.partyLedger.table.reference') }}
                </th>
                <th class="px-3 py-2.5 text-end font-medium">
                  {{ t('finance.partyLedger.table.amount') }}
                </th>
                <th class="px-3 py-2.5 font-medium">{{ t('finance.partyLedger.table.proof') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(entry, index) in ledger.entries"
                :key="index"
                class="border-ligne border-b last:border-0"
              >
                <td class="px-3 py-2.5">{{ entry.date }}</td>
                <td class="px-3 py-2.5">{{ t(`finance.partyLedger.entryTypes.${entry.type}`) }}</td>
                <td class="px-3 py-2.5">{{ entry.reference || '—' }}</td>
                <td class="px-3 py-2.5 text-end"><MonoValue :value="formatMoney(entry.amount)" /></td>
                <td class="px-3 py-2.5">
                  <button
                    v-if="entry.proof_url"
                    type="button"
                    class="text-bitume underline"
                    @click="previewUrl = entry.proof_url"
                  >
                    {{ t('finance.partyLedger.viewProof') }}
                  </button>
                  <span v-else class="text-texte-3">—</span>
                </td>
              </tr>
              <tr v-if="ledger.entries.length === 0">
                <td colspan="5" class="text-texte-3 px-3 py-8 text-center">
                  {{ t('finance.partyLedger.noEntries') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
    </template>

    <Modal
      v-if="showPaymentModal && ledger"
      :title="t('finance.debtPayment.title')"
      max-width="max-w-3xl"
      @close="showPaymentModal = false"
    >
      <DebtPaymentForm
        initial-debt-type="transporter"
        :initial-debt-id="ledger.transporter.id"
        lock-debt-type
        lock-debt
        @success="onPaymentSuccess"
        @cancel="showPaymentModal = false"
      />
    </Modal>

    <Modal
      v-if="showAdvanceForm && ledger"
      :title="t('finance.advanceForm.title')"
      max-width="max-w-3xl"
      @close="showAdvanceForm = false"
    >
      <AdvanceForm
        initial-party-type="transporter"
        :initial-party-id="ledger.transporter.id"
        lock-party-type
        lock-party
        @success="onAdvanceSaved"
        @cancel="showAdvanceForm = false"
      />
    </Modal>

    <Modal
      v-if="previewUrl"
      :title="t('finance.partyLedger.table.proof')"
      max-width="max-w-3xl"
      @close="previewUrl = null"
    >
      <img :src="previewUrl" class="max-h-[80vh] w-full rounded-lg object-contain" />
      <div class="mt-4 flex justify-end">
        <Button variant="ghost" @click="previewUrl = null">{{ t('common.close') }}</Button>
      </div>
    </Modal>
  </div>
</template>
