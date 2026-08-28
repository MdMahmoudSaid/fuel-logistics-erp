<script setup lang="ts">
// Task 7 (client modifications plan): Shareholders / Associates domain.
// A single top-level page (not an overlay) covering every action the
// brief lists: shareholder CRUD with participation percent, profit
// distribution by period with calculated shares, advances/debts between
// associates (loans), shareholder withdrawals, and a per-shareholder
// ledger (remaining due + loan balances) - backend/apps/finance/views.py
// ShareholderViewSet/ShareholderProfitDistributionViewSet/
// ShareholderLoanViewSet/ShareholderWithdrawalViewSet.
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import {
  fetchShareholderLedger,
  fetchShareholderProfitPreview,
  recordShareholderLoanRepayment,
  shareholderDistributionResource,
  shareholderLoanResource,
  shareholderResource,
  shareholderWithdrawalResource,
  validateShareholderDistribution,
} from './api'
import type {
  Shareholder,
  ShareholderLedger,
  ShareholderLoan,
  ShareholderProfitDistribution,
  ShareholderProfitPreview,
  ShareholderWithdrawal,
} from './types'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import EntityForm from '@/components/master-data/EntityForm.vue'
import type { FieldSchema } from '@/components/master-data/types'
import { formatMoney } from '@/utils/currency'

const { t } = useI18n()

type ShareholderTab = 'summary' | 'associates' | 'distributions' | 'loans' | 'withdrawals' | 'ledger'
const activeTab = ref<ShareholderTab>('summary')
const tabs: { key: ShareholderTab; label: string }[] = [
  { key: 'summary', label: 'Résumé' },
  { key: 'associates', label: 'Associés' },
  { key: 'distributions', label: 'Répartition des bénéfices' },
  { key: 'loans', label: 'Avances' },
  { key: 'withdrawals', label: 'Retraits' },
  { key: 'ledger', label: 'Grand livre' },
]

function extractErrorMessage(e: unknown, fallback: string): string {
  const data = (e as { response?: { data?: Record<string, unknown> } })?.response?.data
  if (!data) return fallback
  const detail = data.detail ?? data.non_field_errors ?? Object.values(data)[0]
  const message = Array.isArray(detail) ? detail[0] : detail
  return typeof message === 'string' ? message : fallback
}

const today = () => new Date().toISOString().slice(0, 10)

// --- Shared reference data -------------------------------------------------

const shareholders = ref<Shareholder[]>([])
const activeShareholders = computed(() => shareholders.value.filter((s) => s.is_active))

const bankAccountResource = createResourceApi<{ id: number; name: string }>('/bank-accounts/')
const cashAccountResource = createResourceApi<{ id: number; name: string }>('/cash-accounts/')
const bankAccounts = ref<{ id: number; name: string }[]>([])
const cashAccounts = ref<{ id: number; name: string }[]>([])

async function loadShareholders() {
  const data = await shareholderResource.list()
  shareholders.value = [...data.results]
}

onMounted(async () => {
  await Promise.all([
    loadShareholders(),
    bankAccountResource.list().then((r) => (bankAccounts.value = r.results)),
    cashAccountResource.list().then((r) => (cashAccounts.value = r.results)),
    loadDistributions(),
    loadLoans(),
    loadWithdrawals(),
    loadPreview(),
  ])
})

// --- Live profit preview (read-only, indicative) ----------------------------
// backend/apps/finance/services.py ShareholderProfitPreviewService - never
// stored, never gates a withdrawal. Shown as a clearly-labelled banner so
// it can never be mistaken for a validated ShareholderProfitDistribution,
// and used to pre-fill (still-editable) the distribution form below.

const preview = ref<ShareholderProfitPreview | null>(null)

async function loadPreview() {
  try {
    preview.value = await fetchShareholderProfitPreview()
    // Pre-fill (not lock) the distribution form's total_profit from the
    // same engine, so a manager isn't typing a number from memory - still
    // freely editable before submit.
    if (!distributionForm.value.total_profit && preview.value) {
      distributionForm.value.total_profit = preview.value.current_profit
    }
  } catch {
    preview.value = null
  }
}

// --- Section 1: Shareholders ------------------------------------------------

const showShareholderForm = ref(false)
const editingShareholderId = ref<number | null>(null)
const shareholderFormValue = ref<Record<string, unknown>>({})
const shareholderError = ref('')

const shareholderFields = computed<FieldSchema[]>(() => [
  { key: 'name', label: t('masterData.fields.name'), type: 'text', required: true },
  {
    key: 'participation_percent',
    label: t('masterData.fields.participationPercent'),
    type: 'number',
    required: true,
  },
  {
    key: 'contribution',
    label: t('masterData.fields.contribution'),
    type: 'number',
    required: true,
  },
  { key: 'phone', label: t('masterData.fields.phone'), type: 'phone' },
  { key: 'notes', label: t('masterData.fields.notes'), type: 'textarea' },
  { key: 'is_active', label: t('masterData.fields.active'), type: 'checkbox' },
])

function openCreateShareholder() {
  editingShareholderId.value = null
  shareholderFormValue.value = { is_active: true, contribution: '0.00' }
  shareholderError.value = ''
  showShareholderForm.value = true
}

function openEditShareholder(shareholder: Shareholder) {
  editingShareholderId.value = shareholder.id
  shareholderFormValue.value = { ...shareholder }
  shareholderError.value = ''
  showShareholderForm.value = true
}

async function onShareholderSubmit() {
  try {
    if (editingShareholderId.value === null) {
      await shareholderResource.create(shareholderFormValue.value)
    } else {
      await shareholderResource.update(editingShareholderId.value, shareholderFormValue.value)
    }
    showShareholderForm.value = false
    await loadShareholders()
  } catch (e) {
    shareholderError.value = extractErrorMessage(e, t('finance.shareholder.saveError'))
  }
}

// --- Section 2: Profit distributions ---------------------------------------

const distributions = ref<ShareholderProfitDistribution[]>([])
const distributionForm = ref({ period_start: today(), period_end: today(), total_profit: '' })
const distributionError = ref('')
const savingDistribution = ref(false)
const expandedDistributionId = ref<number | null>(null)

async function loadDistributions() {
  const data = await shareholderDistributionResource.list()
  distributions.value = [...data.results]
}

async function onCreateDistribution() {
  savingDistribution.value = true
  distributionError.value = ''
  try {
    const created = await shareholderDistributionResource.create(distributionForm.value)
    distributionForm.value = { period_start: today(), period_end: today(), total_profit: '' }
    expandedDistributionId.value = created.id
    await loadDistributions()
  } catch (e) {
    distributionError.value = extractErrorMessage(
      e,
      t('finance.shareholder.distribution.saveError'),
    )
  } finally {
    savingDistribution.value = false
  }
}

async function onValidateDistribution(distribution: ShareholderProfitDistribution) {
  try {
    await validateShareholderDistribution(distribution.id)
    await loadDistributions()
  } catch (e) {
    distributionError.value = extractErrorMessage(
      e,
      t('finance.shareholder.distribution.saveError'),
    )
  }
}

function toggleExpandDistribution(id: number) {
  expandedDistributionId.value = expandedDistributionId.value === id ? null : id
}

// --- Section 3: Loans between associates ------------------------------------

const loans = ref<ShareholderLoan[]>([])
const loanForm = ref({ borrower: '', lender: '', amount: '', date: today(), notes: '' })
const loanError = ref('')
const savingLoan = ref(false)
const repaymentInput = ref<Record<number, string>>({})

async function loadLoans() {
  const data = await shareholderLoanResource.list()
  loans.value = [...data.results]
}

async function onCreateLoan() {
  savingLoan.value = true
  loanError.value = ''
  try {
    await shareholderLoanResource.create({
      borrower: Number(loanForm.value.borrower),
      lender: Number(loanForm.value.lender),
      amount: loanForm.value.amount,
      date: loanForm.value.date,
      notes: loanForm.value.notes,
    })
    loanForm.value = { borrower: '', lender: '', amount: '', date: today(), notes: '' }
    await loadLoans()
  } catch (e) {
    loanError.value = extractErrorMessage(e, t('finance.shareholder.loan.saveError'))
  } finally {
    savingLoan.value = false
  }
}

async function onRecordRepayment(loan: ShareholderLoan) {
  const extra = Number(repaymentInput.value[loan.id] || '0')
  if (!extra || extra <= 0) return
  try {
    // Send the increment, never a client-computed absolute total (Task 7
    // fix: loan-repayment lost-update race) - the backend applies it
    // under select_for_update() so two repayments entered close together
    // (two tabs, two people) can never silently overwrite each other the
    // way PATCHing `current + extra` from a stale read could.
    await recordShareholderLoanRepayment(loan.id, extra.toFixed(2))
    repaymentInput.value[loan.id] = ''
    await loadLoans()
  } catch (e) {
    loanError.value = extractErrorMessage(e, t('finance.shareholder.loan.saveError'))
  }
}

function loanStatusVariant(status: string) {
  if (status === 'REPAID') return 'livre' as const
  if (status === 'PARTIALLY_REPAID') return 'transit' as const
  return 'neutre' as const
}

// --- Section 4: Withdrawals --------------------------------------------------

const withdrawals = ref<ShareholderWithdrawal[]>([])
const withdrawalForm = ref({
  shareholder: '',
  profit_share: '',
  amount: '',
  date: today(),
  account_type: 'cash' as 'bank' | 'cash',
  account_id: '',
  notes: '',
})
const withdrawalError = ref('')
const savingWithdrawal = ref(false)

const withdrawalAccountOptions = computed(() =>
  withdrawalForm.value.account_type === 'bank' ? bankAccounts.value : cashAccounts.value,
)

// Shares with something left to withdraw, for the selected shareholder -
// the picker only ever offers shares that still owe money.
const availableSharesForWithdrawal = computed(() => {
  const shareholderId = Number(withdrawalForm.value.shareholder)
  if (!shareholderId || !ledger.value || ledger.value.shareholder.id !== shareholderId) return []
  return ledger.value.shares.filter((s) => Number(s.remaining_due) > 0)
})

async function loadWithdrawals() {
  const data = await shareholderWithdrawalResource.list()
  withdrawals.value = [...data.results]
}

async function onCreateWithdrawal() {
  savingWithdrawal.value = true
  withdrawalError.value = ''
  try {
    await shareholderWithdrawalResource.create({
      shareholder: Number(withdrawalForm.value.shareholder),
      profit_share: withdrawalForm.value.profit_share
        ? Number(withdrawalForm.value.profit_share)
        : null,
      amount: withdrawalForm.value.amount,
      date: withdrawalForm.value.date,
      bank_account:
        withdrawalForm.value.account_type === 'bank'
          ? Number(withdrawalForm.value.account_id)
          : null,
      cash_account:
        withdrawalForm.value.account_type === 'cash'
          ? Number(withdrawalForm.value.account_id)
          : null,
      notes: withdrawalForm.value.notes,
    })
    withdrawalForm.value = {
      shareholder: '',
      profit_share: '',
      amount: '',
      date: today(),
      account_type: 'cash',
      account_id: '',
      notes: '',
    }
    await loadWithdrawals()
    if (ledger.value) await loadLedger(ledger.value.shareholder.id)
  } catch (e) {
    withdrawalError.value = extractErrorMessage(e, t('finance.shareholder.withdrawal.saveError'))
  } finally {
    savingWithdrawal.value = false
  }
}

// --- Section 5: Per-shareholder ledger (remaining due + loan balances) -----

const ledgerShareholderId = ref('')
const ledger = ref<ShareholderLedger | null>(null)
const ledgerLoading = ref(false)
const ledgerError = ref('')

async function loadLedger(shareholderId: number) {
  ledgerLoading.value = true
  ledgerError.value = ''
  try {
    ledger.value = await fetchShareholderLedger(shareholderId)
  } catch {
    ledgerError.value = t('finance.shareholder.ledger.loadError')
  } finally {
    ledgerLoading.value = false
  }
}

async function onViewLedger() {
  if (!ledgerShareholderId.value) return
  await loadLedger(Number(ledgerShareholderId.value))
}
</script>

<template>
  <div class="max-w-5xl space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('finance.shareholder.title') }}
      </h1>
    </div>

    <!-- Live profit preview: read-only, clearly marked as indicative - it
         never gates a withdrawal and is never a stored distribution. -->
    <div v-if="preview" class="border-ecart bg-ecart-tint rounded-xl border p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <Badge variant="transit">{{ t('finance.shareholder.preview.badge') }}</Badge>
          <p class="text-texte-2 text-sm">{{ t('finance.shareholder.preview.notice') }}</p>
        </div>
        <MonoValue
          class="text-lg font-semibold"
          :value="formatMoney(preview.current_profit)"
        />
      </div>
      <div v-if="preview.shareholders.length" class="mt-3 flex flex-wrap gap-4">
        <div v-for="row in preview.shareholders" :key="row.shareholder_id" class="text-sm">
          <span class="text-texte-2">{{ row.name }} ({{ row.participation_percent }}%):</span>
          <MonoValue class="ms-1 inline" :value="formatMoney(row.indicative_share)" />
        </div>
      </div>
    </div>

    <div class="border-ligne flex gap-2 overflow-x-auto border-b pb-2">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="rounded-lg px-3 py-2 text-sm font-medium whitespace-nowrap"
        :class="activeTab === tab.key ? 'bg-bitume text-sable' : 'text-texte-2 hover:bg-white'"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <section v-if="activeTab === 'summary'" class="grid gap-3 md:grid-cols-2">
      <div
        v-for="row in preview?.shareholders ?? []"
        :key="row.shareholder_id"
        class="border-ligne rounded-lg border bg-white p-4"
      >
        <p class="text-texte font-semibold">{{ row.name }}</p>
        <p class="text-texte-2 text-sm">{{ row.participation_percent }} %</p>
        <p class="mt-3 text-sm">Bénéfice indicatif actuel</p>
        <MonoValue class="text-lg font-semibold" align="left" :value="formatMoney(row.indicative_share)" />
      </div>
    </section>

    <!-- Section 1: Shareholders -->
    <Card v-if="activeTab === 'associates'" :title="t('finance.shareholder.listTitle')">
      <template #actions>
        <Button variant="primary" @click="openCreateShareholder">{{ t('masterData.add') }}</Button>
      </template>

      <table class="w-full text-start text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">{{ t('masterData.fields.name') }}</th>
            <th class="px-3 py-2.5 text-end font-medium">
              {{ t('masterData.fields.participationPercent') }}
            </th>
            <th class="px-3 py-2.5 text-end font-medium">
              {{ t('masterData.fields.contribution') }}
            </th>
            <th class="px-3 py-2.5 font-medium">{{ t('masterData.fields.phone') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('masterData.fields.active') }}</th>
            <th class="px-3 py-2.5"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in shareholders" :key="s.id" class="border-ligne border-b last:border-0">
            <td class="px-3 py-2.5">{{ s.name }}</td>
            <td class="px-3 py-2.5 text-end">
              <MonoValue :value="`${s.participation_percent}%`" />
            </td>
            <td class="px-3 py-2.5 text-end">
              <MonoValue :value="formatMoney(s.contribution)" />
            </td>
            <td class="px-3 py-2.5">{{ s.phone || '—' }}</td>
            <td class="px-3 py-2.5">
              <Badge :variant="s.is_active ? 'livre' : 'neutre'">
                {{ s.is_active ? t('masterData.statusActive') : t('masterData.statusInactive') }}
              </Badge>
            </td>
            <td class="px-3 py-2.5 text-end">
              <Button variant="ghost" @click="openEditShareholder(s)">{{
                t('masterData.edit')
              }}</Button>
            </td>
          </tr>
          <tr v-if="shareholders.length === 0">
            <td colspan="6" class="text-texte-3 px-3 py-8 text-center">
              {{ t('masterData.noRecords') }}
            </td>
          </tr>
        </tbody>
      </table>
    </Card>

    <!-- Section 2: Profit distributions -->
    <Card
      v-if="activeTab === 'distributions'"
      :title="t('finance.shareholder.distribution.title')"
    >
      <p v-if="distributionError" class="text-critique mb-3 text-sm">{{ distributionError }}</p>

      <form class="mb-5 grid grid-cols-4 gap-3" @submit.prevent="onCreateDistribution">
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="period_start">
            {{ t('finance.shareholder.distribution.periodStart') }}
          </label>
          <input
            id="period_start"
            v-model="distributionForm.period_start"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="period_end">
            {{ t('finance.shareholder.distribution.periodEnd') }}
          </label>
          <input
            id="period_end"
            v-model="distributionForm.period_end"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="total_profit">
            {{ t('finance.shareholder.distribution.totalProfit') }}
          </label>
          <input
            id="total_profit"
            v-model="distributionForm.total_profit"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div class="flex items-end">
          <Button type="submit" variant="primary" class="w-full" :loading="savingDistribution">
            {{ t('finance.shareholder.distribution.create') }}
          </Button>
        </div>
      </form>

      <table class="w-full text-start text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">
              {{ t('finance.shareholder.distribution.period') }}
            </th>
            <th class="px-3 py-2.5 text-end font-medium">
              {{ t('finance.shareholder.distribution.totalProfit') }}
            </th>
            <th class="px-3 py-2.5 font-medium">
              {{ t('finance.shareholder.distribution.status') }}
            </th>
            <th class="px-3 py-2.5"></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="d in distributions" :key="d.id">
            <tr
              class="border-ligne hover:bg-sable cursor-pointer border-b"
              @click="toggleExpandDistribution(d.id)"
            >
              <td class="px-3 py-2.5">{{ d.period_start }} — {{ d.period_end }}</td>
              <td class="px-3 py-2.5 text-end">
                <MonoValue :value="formatMoney(d.total_profit)" />
              </td>
              <td class="px-3 py-2.5">
                <Badge :variant="d.status === 'VALIDATED' ? 'livre' : 'transit'">
                  {{ t(`finance.shareholder.distribution.statusValues.${d.status}`) }}
                </Badge>
              </td>
              <td class="px-3 py-2.5 text-end">
                <Button
                  v-if="d.status === 'DRAFT'"
                  variant="ghost"
                  @click.stop="onValidateDistribution(d)"
                >
                  {{ t('finance.shareholder.distribution.validate') }}
                </Button>
              </td>
            </tr>
            <tr v-if="expandedDistributionId === d.id" class="border-ligne border-b bg-sable/40">
              <td colspan="4" class="px-3 py-3">
                <table class="w-full text-start text-sm">
                  <thead>
                    <tr class="text-texte-2">
                      <th class="px-3 py-1.5 font-medium">
                        {{ t('finance.shareholder.distribution.shareholder') }}
                      </th>
                      <th class="px-3 py-1.5 text-end font-medium">
                        {{ t('finance.shareholder.distribution.percent') }}
                      </th>
                      <th class="px-3 py-1.5 text-end font-medium">
                        {{ t('finance.shareholder.distribution.amountDue') }}
                      </th>
                      <th class="px-3 py-1.5 text-end font-medium">
                        {{ t('finance.shareholder.distribution.remainingDue') }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="share in d.shares" :key="share.id">
                      <td class="px-3 py-1.5">{{ share.shareholder_detail?.name }}</td>
                      <td class="px-3 py-1.5 text-end">
                        <MonoValue :value="`${share.percent_snapshot}%`" />
                      </td>
                      <td class="px-3 py-1.5 text-end">
                        <MonoValue :value="formatMoney(share.amount_due)" />
                      </td>
                      <td class="px-3 py-1.5 text-end">
                        <MonoValue :value="formatMoney(share.remaining_due)" />
                      </td>
                    </tr>
                  </tbody>
                </table>
              </td>
            </tr>
          </template>
          <tr v-if="distributions.length === 0">
            <td colspan="4" class="text-texte-3 px-3 py-8 text-center">
              {{ t('masterData.noRecords') }}
            </td>
          </tr>
        </tbody>
      </table>
    </Card>

    <!-- Section 3: Loans between associates -->
    <Card v-if="activeTab === 'loans'" :title="t('finance.shareholder.loan.title')">
      <p v-if="loanError" class="text-critique mb-3 text-sm">{{ loanError }}</p>

      <form class="mb-5 grid grid-cols-4 gap-3" @submit.prevent="onCreateLoan">
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="lender">
            {{ t('finance.shareholder.loan.lender') }}
          </label>
          <select
            id="lender"
            v-model="loanForm.lender"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.shareholder.selectShareholder') }}</option>
            <option v-for="s in shareholders" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="borrower">
            {{ t('finance.shareholder.loan.borrower') }}
          </label>
          <select
            id="borrower"
            v-model="loanForm.borrower"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.shareholder.selectShareholder') }}</option>
            <option v-for="s in shareholders" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="loan_amount">
            {{ t('finance.shareholder.loan.amount') }}
          </label>
          <input
            id="loan_amount"
            v-model="loanForm.amount"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="loan_date">
            {{ t('finance.shareholder.loan.date') }}
          </label>
          <input
            id="loan_date"
            v-model="loanForm.date"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div class="col-span-3 space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="loan_notes">
            {{ t('masterData.fields.notes') }}
          </label>
          <input
            id="loan_notes"
            v-model="loanForm.notes"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div class="flex items-end">
          <Button type="submit" variant="primary" class="w-full" :loading="savingLoan">
            {{ t('finance.shareholder.loan.record') }}
          </Button>
        </div>
      </form>

      <table class="w-full text-start text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">{{ t('finance.shareholder.loan.lender') }}</th>
            <th class="px-3 py-2.5 font-medium">{{ t('finance.shareholder.loan.borrower') }}</th>
            <th class="px-3 py-2.5 text-end font-medium">
              {{ t('finance.shareholder.loan.amount') }}
            </th>
            <th class="px-3 py-2.5 text-end font-medium">
              {{ t('finance.shareholder.loan.remaining') }}
            </th>
            <th class="px-3 py-2.5 font-medium">{{ t('finance.shareholder.loan.status') }}</th>
            <th class="px-3 py-2.5 font-medium">
              {{ t('finance.shareholder.loan.recordRepayment') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="loan in loans" :key="loan.id" class="border-ligne border-b last:border-0">
            <td class="px-3 py-2.5">{{ loan.lender_detail?.name }}</td>
            <td class="px-3 py-2.5">{{ loan.borrower_detail?.name }}</td>
            <td class="px-3 py-2.5 text-end">
              <MonoValue :value="formatMoney(loan.amount)" />
            </td>
            <td class="px-3 py-2.5 text-end">
              <MonoValue :value="formatMoney(loan.remaining_amount)" />
            </td>
            <td class="px-3 py-2.5">
              <Badge :variant="loanStatusVariant(loan.status)">
                {{ t(`finance.shareholder.loan.statusValues.${loan.status}`) }}
              </Badge>
            </td>
            <td class="px-3 py-2.5">
              <div v-if="loan.status !== 'REPAID'" class="flex items-center gap-2">
                <input
                  v-model="repaymentInput[loan.id]"
                  type="number"
                  step="0.01"
                  min="0.01"
                  :placeholder="t('finance.shareholder.loan.repaymentAmount')"
                  class="border-ligne-forte h-10 w-28 rounded-lg border bg-white px-2 text-sm focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                />
                <Button variant="ghost" @click="onRecordRepayment(loan)">
                  {{ t('common.save') }}
                </Button>
              </div>
            </td>
          </tr>
          <tr v-if="loans.length === 0">
            <td colspan="6" class="text-texte-3 px-3 py-8 text-center">
              {{ t('masterData.noRecords') }}
            </td>
          </tr>
        </tbody>
      </table>
    </Card>

    <!-- Section 4: Shareholder withdrawals -->
    <Card
      v-if="activeTab === 'withdrawals'"
      :title="t('finance.shareholder.withdrawal.title')"
    >
      <p v-if="withdrawalError" class="text-critique mb-3 text-sm">{{ withdrawalError }}</p>

      <form class="mb-5 grid grid-cols-4 gap-3" @submit.prevent="onCreateWithdrawal">
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="wd_shareholder">
            {{ t('finance.shareholder.withdrawal.shareholder') }}
          </label>
          <select
            id="wd_shareholder"
            v-model="withdrawalForm.shareholder"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            @change="withdrawalForm.profit_share = ''"
          >
            <option value="" disabled>{{ t('finance.shareholder.selectShareholder') }}</option>
            <option v-for="s in activeShareholders" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="wd_share">
            {{ t('finance.shareholder.withdrawal.profitShare') }}
          </label>
          <select
            id="wd_share"
            v-model="withdrawalForm.profit_share"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="">{{ t('finance.shareholder.withdrawal.general') }}</option>
            <option v-for="share in availableSharesForWithdrawal" :key="share.id" :value="share.id">
              {{ share.period_start }} — {{ share.period_end }} ({{ share.remaining_due }})
            </option>
          </select>
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="wd_amount">
            {{ t('finance.shareholder.withdrawal.amount') }}
          </label>
          <input
            id="wd_amount"
            v-model="withdrawalForm.amount"
            type="number"
            step="0.01"
            min="0.01"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="wd_date">
            {{ t('finance.shareholder.withdrawal.date') }}
          </label>
          <input
            id="wd_date"
            v-model="withdrawalForm.date"
            type="date"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="wd_account_type">
            {{ t('finance.shareholder.withdrawal.accountType') }}
          </label>
          <select
            id="wd_account_type"
            v-model="withdrawalForm.account_type"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            @change="withdrawalForm.account_id = ''"
          >
            <option value="bank">{{ t('finance.transfer.bank') }}</option>
            <option value="cash">{{ t('finance.transfer.cash') }}</option>
          </select>
        </div>
        <div class="space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="wd_account_id">
            {{ t('finance.shareholder.withdrawal.account') }}
          </label>
          <select
            id="wd_account_id"
            v-model="withdrawalForm.account_id"
            required
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.transfer.selectAccount') }}</option>
            <option v-for="a in withdrawalAccountOptions" :key="a.id" :value="a.id">
              {{ a.name }}
            </option>
          </select>
        </div>
        <div class="col-span-2 space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="wd_notes">
            {{ t('masterData.fields.notes') }}
          </label>
          <input
            id="wd_notes"
            v-model="withdrawalForm.notes"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          />
        </div>
        <div class="flex items-end">
          <Button type="submit" variant="primary" class="w-full" :loading="savingWithdrawal">
            {{ t('finance.shareholder.withdrawal.record') }}
          </Button>
        </div>
      </form>

      <table class="w-full text-start text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">
              {{ t('finance.shareholder.withdrawal.shareholder') }}
            </th>
            <th class="px-3 py-2.5 font-medium">{{ t('finance.shareholder.withdrawal.date') }}</th>
            <th class="px-3 py-2.5 text-end font-medium">
              {{ t('finance.shareholder.withdrawal.amount') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in withdrawals" :key="w.id" class="border-ligne border-b last:border-0">
            <td class="px-3 py-2.5">{{ w.shareholder_detail?.name }}</td>
            <td class="px-3 py-2.5">{{ w.date }}</td>
            <td class="px-3 py-2.5 text-end">
              <MonoValue :value="formatMoney(w.amount)" />
            </td>
          </tr>
          <tr v-if="withdrawals.length === 0">
            <td colspan="3" class="text-texte-3 px-3 py-8 text-center">
              {{ t('masterData.noRecords') }}
            </td>
          </tr>
        </tbody>
      </table>
    </Card>

    <!-- Section 5: Per-shareholder ledger -->
    <Card v-if="activeTab === 'ledger'" :title="t('finance.shareholder.ledger.title')">
      <div class="mb-5 flex items-end gap-3">
        <div class="flex-1 space-y-1.5">
          <label class="text-texte-2 text-sm font-medium" for="ledger_shareholder">
            {{ t('finance.shareholder.selectShareholder') }}
          </label>
          <select
            id="ledger_shareholder"
            v-model="ledgerShareholderId"
            class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <option value="" disabled>{{ t('finance.shareholder.selectShareholder') }}</option>
            <option v-for="s in shareholders" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </div>
        <Button variant="primary" @click="onViewLedger">{{
          t('finance.shareholder.ledger.view')
        }}</Button>
      </div>

      <p v-if="ledgerError" class="text-critique text-sm">{{ ledgerError }}</p>
      <p v-else-if="ledgerLoading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

      <template v-else-if="ledger">
        <section class="mb-5 grid grid-cols-5 gap-4">
          <div class="border-ligne rounded-xl border p-4">
            <p class="text-texte-2 text-xs">{{ t('finance.shareholder.ledger.totalDue') }}</p>
            <MonoValue
              class="text-lg font-semibold"
              align="left"
              :value="formatMoney(ledger.total_amount_due)"
            />
          </div>
          <div class="border-ligne rounded-xl border p-4">
            <p class="text-texte-2 text-xs">{{ t('finance.shareholder.ledger.totalWithdrawn') }}</p>
            <MonoValue
              class="text-lg font-semibold"
              align="left"
              :value="formatMoney(ledger.total_withdrawn)"
            />
          </div>
          <div class="border-ligne rounded-xl border p-4">
            <p class="text-texte-2 text-xs">{{ t('finance.shareholder.ledger.remainingDue') }}</p>
            <MonoValue
              class="text-lg font-semibold"
              align="left"
              :class="Number(ledger.remaining_due) > 0 ? 'text-ecart' : 'text-livre'"
              :value="formatMoney(ledger.remaining_due)"
            />
          </div>
          <div class="border-ligne rounded-xl border p-4">
            <p class="text-texte-2 text-xs">{{ t('finance.shareholder.ledger.netLoanBalance') }}</p>
            <MonoValue
              class="text-lg font-semibold"
              align="left"
              :value="formatMoney(ledger.net_loan_balance)"
            />
          </div>
          <div class="border-bitume bg-sable/40 rounded-xl border-2 p-4">
            <p class="text-texte-2 text-xs">
              {{ t('finance.shareholder.ledger.availableBalance') }}
            </p>
            <MonoValue
              class="text-lg font-semibold"
              align="left"
              :class="Number(ledger.available_balance) > 0 ? 'text-livre' : 'text-critique'"
              :value="formatMoney(ledger.available_balance)"
            />
          </div>
        </section>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <h3 class="text-texte-2 mb-2 text-sm font-medium">
              {{ t('finance.shareholder.ledger.loansLent') }}
            </h3>
            <table class="w-full text-start text-sm">
              <tbody>
                <tr v-for="loan in ledger.loans_lent" :key="loan.id" class="border-ligne border-b">
                  <td class="px-2 py-1.5">{{ loan.borrower_name }}</td>
                  <td class="px-2 py-1.5 text-end">
                    <MonoValue :value="formatMoney(loan.remaining_amount)" />
                  </td>
                </tr>
                <tr v-if="ledger.loans_lent.length === 0">
                  <td class="text-texte-3 px-2 py-4 text-center">
                    {{ t('masterData.noRecords') }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div>
            <h3 class="text-texte-2 mb-2 text-sm font-medium">
              {{ t('finance.shareholder.ledger.loansBorrowed') }}
            </h3>
            <table class="w-full text-start text-sm">
              <tbody>
                <tr
                  v-for="loan in ledger.loans_borrowed"
                  :key="loan.id"
                  class="border-ligne border-b"
                >
                  <td class="px-2 py-1.5">{{ loan.lender_name }}</td>
                  <td class="px-2 py-1.5 text-end">
                    <MonoValue :value="formatMoney(loan.remaining_amount)" />
                  </td>
                </tr>
                <tr v-if="ledger.loans_borrowed.length === 0">
                  <td class="text-texte-3 px-2 py-4 text-center">
                    {{ t('masterData.noRecords') }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </Card>

    <div
      v-if="showShareholderForm"
      class="fixed inset-0 z-30 flex items-center justify-center bg-black/40"
    >
      <div class="bg-surface border-ligne w-full max-w-md rounded-xl border p-6">
        <h2 class="font-display mb-4 text-lg leading-none font-semibold uppercase">
          {{ editingShareholderId === null ? t('masterData.new') : t('masterData.edit') }}
          {{ t('finance.shareholder.listTitle') }}
        </h2>
        <p v-if="shareholderError" class="text-critique mb-2 text-sm">{{ shareholderError }}</p>
        <EntityForm
          v-model="shareholderFormValue"
          :fields="shareholderFields"
          @submit="onShareholderSubmit"
          @cancel="showShareholderForm = false"
        />
      </div>
    </div>
  </div>
</template>
