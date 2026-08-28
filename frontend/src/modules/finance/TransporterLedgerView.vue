<script setup lang="ts">
// docs/PHASE_5_PLAN.md Etape 8/10: gross fees earned, loss deductions,
// advances consumed and what's already settled for one transporter
// (guide Section 1.5/8.6: "earned - deductions - advances - payments =
// transporter outstanding"), backed by GET /api/transporters/{id}/ledger/.
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { fetchTransporterLedger } from './api'
import type { TransporterLedger } from './types'
import { formatMoney } from '@/utils/currency'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import DebtPaymentForm from './DebtPaymentForm.vue'
import Modal from '@/components/ui/Modal.vue'
import MonoValue from '@/components/ui/MonoValue.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const ledger = ref<TransporterLedger | null>(null)
const loading = ref(true)
const error = ref('')
const showPaymentModal = ref(false)

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

async function onPaymentSuccess() {
  showPaymentModal.value = false
  await load()
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
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('finance.transporterLedger.title', { name: ledger?.transporter.name ?? '…' }) }}
      </h1>
      <div class="flex gap-2">
        <Button v-if="ledger" variant="primary" @click="showPaymentModal = true">
          {{ t('finance.transporterLedger.newPayment') }}
        </Button>
        <Button variant="ghost" @click="router.push({ name: 'transporters' })">
          {{ t('finance.transporterLedger.back') }}
        </Button>
      </div>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else-if="ledger">
      <section class="grid gap-3 md:grid-cols-5">
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.transporterLedger.grossEarned') }}
          </p>
          <MonoValue class="font-semibold" align="left" :value="formatMoney(ledger.gross_amount)" />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.transporterLedger.deductions') }}
          </p>
          <MonoValue
            class="text-critique font-semibold"
            align="left"
            :value="'− ' + formatMoney(ledger.deductions)"
          />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.transporterLedger.advancesApplied') }}
          </p>
          <MonoValue
            class="text-critique font-semibold"
            align="left"
            :value="'− ' + formatMoney(ledger.advances_applied)"
          />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.transporterLedger.alreadySettled') }}
          </p>
          <MonoValue class="font-semibold" align="left" :value="formatMoney(ledger.settled)" />
        </div>
        <div class="border-ligne rounded-lg border bg-white p-4">
          <p class="text-texte-2 text-xs font-semibold uppercase">
            {{ t('finance.transporterLedger.netOutstanding') }}
          </p>
          <MonoValue
            class="font-semibold"
            align="left"
            :class="Number(ledger.net_outstanding) > 0 ? 'text-ecart' : 'text-livre'"
            :value="formatMoney(ledger.net_outstanding)"
          />
        </div>
      </section>

      <Card :title="t('finance.transporterLedger.settlementsByTrip')">
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
            </tr>
            <tr v-if="ledger.payments.length === 0">
              <td colspan="5" class="text-texte-3 px-2 py-4 text-center">
                {{ t('finance.transporterLedger.noSettlements') }}
              </td>
            </tr>
          </tbody>
        </table>
      </Card>

      <Card :title="t('finance.transporterLedger.advances')">
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
      </Card>
    </template>

    <Modal
      v-if="showPaymentModal && ledger"
      :title="t('finance.debtPayment.title')"
      max-width="max-w-2xl"
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
  </div>
</template>
