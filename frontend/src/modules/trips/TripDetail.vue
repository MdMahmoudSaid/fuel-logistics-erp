<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  tripResource,
  fetchAllowedTripStatuses,
  fetchTripHistory,
  fetchTripMargin,
  postTripStatus,
} from './api'
import { translateApiError } from '@/i18n/apiErrors'
import DeliveryControlForm from './DeliveryControlForm.vue'
import type { Trip, TripMargin, TripStatus, TripStatusHistoryEntry } from './types'
import { fetchReport } from '@/modules/reports/api'
import { lossSeverityTone, type LossReportRow } from '@/modules/dashboard/aggregate'
import GaugeBar from '@/components/ui/GaugeBar.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Modal from '@/components/ui/Modal.vue'
import { useTripStatusLabel } from './tripStatusLabels'
import { cancelExpense, expenseResource } from '@/modules/finance/api'
import { transportPaymentResource } from '@/modules/finance/api'
import ExpenseForm from '@/modules/finance/ExpenseForm.vue'
import TransportPaymentForm from '@/modules/finance/TransportPaymentForm.vue'
import AssignCustomerForm from './AssignCustomerForm.vue'
import type { Expense } from '@/modules/finance/types'
import type { ExpenseCategory, TransportPayment } from '@/modules/finance/types'
import { formatMoney, formatUnitMoney, formatQuantity } from '@/utils/currency'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()
const statusLabel = useTripStatusLabel()

const tripId = computed(() => Number(route.params.id))

const trip = ref<Trip | null>(null)
const history = ref<TripStatusHistoryEntry[]>([])
const loading = ref(true)
const error = ref('')
const previewUrl = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    ;[trip.value, history.value] = await Promise.all([
      tripResource.get!(tripId.value),
      fetchTripHistory(tripId.value),
    ])
  } catch {
    error.value = t('trips.detail.loadError')
  } finally {
    loading.value = false
  }
}

onMounted(load)

// "Frais du trajet": Expense has no direct FK to Trip, only the generic
// ExpenseAllocation link - GET /api/expenses/?trip=<id> (backend/apps/
// finance/views.py ExpenseViewSet.get_queryset()) does that lookup.
const expenses = ref<Expense[]>([])
const transportPayments = ref<TransportPayment[]>([])
const expensesError = ref('')
const showExpenseForm = ref(false)
const automaticExpense = ref<{
  title: string
  category: ExpenseCategory
} | null>(null)
const canManageExpenses = computed(() => auth.can('finance', 'create'))
// Phase 5: POST /api/expenses/{id}/cancel/ requires the "cancel" tier
// (backend/apps/accounts/permissions.py ACTION_MAP falls back to the raw
// action name "cancel", same tier already gating destroy/hard-delete
// elsewhere) - not every finance-create role has it.
const canCancelExpenses = computed(() => auth.can('finance', 'cancel'))
const cancellingExpenseId = ref<number | null>(null)

// Client modification Task 2: transporter fees per litre create payable
// debt - same "finance" module create permission gates both forms.
const showTransportPaymentForm = ref(false)
const automaticTransportTitle = ref<string | null>(null)

// Client modifications plan Task 9 (gap-closure): assign-customer is
// "edit" tier on the "operations" module (backend/apps/accounts/
// permissions.py ACTION_MAP["assign_customer"]), same tier as a trip
// status transition - reuse the same gate rather than introduce a new one.
const canAssignCustomer = computed(() => auth.can('operations', 'edit'))
const showAssignCustomerForm = ref(false)

// Mirrors the backend's own reject-after-sale rule
// (TripCostService.assign_customer_for_sale raises CustomerAlreadySoldError
// once trip.sale exists): margin.available flips true exactly when a Sale
// has been recorded, so "no sale yet" is `margin !== null && !available`.
// The stricter `margin !== null` (vs. `!margin?.available`) hides the
// action while margin is still loading rather than flashing it briefly.
const noSaleYet = computed(() => margin.value !== null && !margin.value.available)
const customsReachedStatuses: TripStatus[] = [
  'CUSTOMS',
  'GOING_TO_COMPANY_STOCK',
  'ARRIVED_AT_COMPANY_STOCK',
  'STOCKED',
  'GOING_TO_CLIENT',
  'ARRIVED_AT_CLIENT',
  'QUANTITY_CONTROL',
  'DELIVERED',
  'COMPLETED',
]
const canShowAssignCustomer = computed(
  () =>
    trip.value?.destination_type === 'COMPANY_STOCK' &&
    customsReachedStatuses.includes(trip.value.status) &&
    canAssignCustomer.value &&
    noSaleYet.value,
)

async function onCustomerAssigned() {
  showAssignCustomerForm.value = false
  await Promise.all([load(), loadMargin()])
  await loadAllowedStatuses()
}

async function onDeliveryConfirmed() {
  await Promise.all([load(), loadMargin()])
  await loadAllowedStatuses()
}

async function loadExpenses() {
  expensesError.value = ''
  try {
    const [expenseData, transportPaymentData] = await Promise.all([
      expenseResource.list({ trip: tripId.value }),
      transportPaymentResource.list({ trip: tripId.value }),
    ])
    expenses.value = expenseData.results
    transportPayments.value = transportPaymentData.results
  } catch {
    expensesError.value = t('trips.detail.expensesLoadError')
  }
}

onMounted(loadExpenses)

// One Expense can be split across several trips (e.g. a monthly customs
// fee) - show the slice allocated to *this* trip, not the expense's total.
function tripAllocation(expense: Expense) {
  return expense.allocations_detail.find(
    (a) => a.content_type_name === 'trip' && a.object_id === tripId.value,
  )
}

async function onExpenseSaved() {
  showExpenseForm.value = false
  automaticExpense.value = null
  await Promise.all([loadExpenses(), loadMargin()])
}

async function onCancelExpense(expense: Expense) {
  cancellingExpenseId.value = expense.id
  expensesError.value = ''
  try {
    await cancelExpense(expense.id)
    await Promise.all([loadExpenses(), loadMargin()])
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    expensesError.value = translateApiError(detail) || t('trips.detail.expensesLoadError')
  } finally {
    cancellingExpenseId.value = null
  }
}

async function onTransportPaymentSaved() {
  showTransportPaymentForm.value = false
  automaticTransportTitle.value = null
  await Promise.all([loadExpenses(), loadMargin()])
}

// TripProfitService.get_cost_breakdown (guide Section 9.1) - only
// available once the trip has a Sale (delivery confirmed), so this also
// gets re-fetched after a status change (onChangeStatus) and after a new
// expense is saved (onExpenseSaved), both of which can flip or move it.
const margin = ref<TripMargin | null>(null)
const marginError = ref('')

async function loadMargin() {
  marginError.value = ''
  try {
    margin.value = await fetchTripMargin(tripId.value)
  } catch {
    marginError.value = t('trips.detail.marginLoadError')
  }
}

onMounted(loadMargin)

// docs/UI_REDESIGN_PLAN.md Etape 6.2: bloc "Jauges" (chargé/livré/écart).
// Pas de champ dédié sur Trip pour la quantité livrée - le DeliveryControl
// associé n'est pas non plus imbriqué dans TripSerializer (backend/apps/
// trips/serializers.py), et il n'existe aucun endpoint de lecture pour un
// DeliveryControl isolé (seule sa création via POST /trips/{id}/delivery-
// control/ est exposée). Le loss-report existant expose déjà ces champs par
// trip_reference - on le réutilise plutôt que d'ajouter un endpoint backend
// pour ce seul affichage.
const deliveryData = ref<LossReportRow | null>(null)

watch(
  () => trip.value?.status,
  async (status) => {
    if (status !== 'DELIVERED' && status !== 'COMPLETED') {
      deliveryData.value = null
      return
    }
    try {
      const report = await fetchReport('loss-report', {})
      const rows = report.rows as unknown as LossReportRow[]
      deliveryData.value = rows.find((row) => row.trip_reference === trip.value?.reference) ?? null
    } catch {
      deliveryData.value = null
    }
  },
)

const deliveredPct = computed(() => {
  if (!deliveryData.value) return 0
  const loaded = Number(deliveryData.value.loaded_quantity)
  return loaded > 0 ? (Number(deliveryData.value.received_quantity) / loaded) * 100 : 0
})
const lossPct = computed(() => {
  if (!deliveryData.value) return 0
  const loaded = Number(deliveryData.value.loaded_quantity)
  return loaded > 0 ? (Number(deliveryData.value.loss_quantity) / loaded) * 100 : 0
})

const canChangeStatus = computed(() => auth.can('operations', 'edit'))

// The backend's TripWorkflowService is the sole authority on which
// transitions are valid from the current status (guide §6.9: "Do not
// hard-code workflow rules in Vue") — every status is offered here and
// whatever the server rejects is surfaced as an error, rather than this
// component re-deriving the transition table.
const nextStatus = ref('')
const statusNotes = ref('')
const changingStatus = ref(false)
const statusError = ref('')
const allowedStatuses = ref<string[]>([])

async function loadAllowedStatuses() {
  if (!trip.value) return
  try {
    allowedStatuses.value = await fetchAllowedTripStatuses(trip.value.id)
  } catch {
    allowedStatuses.value = []
  }
}

watch(
  () => trip.value?.id,
  () => {
    void loadAllowedStatuses()
  },
)

const visibleNextStatuses = computed(() => allowedStatuses.value as TripStatus[])

const automaticExpenseByStatus: Partial<Record<TripStatus, { title: string; category: ExpenseCategory }>> =
  {
    LOADING: { title: t('trips.detail.autoExpense.loading'), category: 'loading' },
    ROAD_TRANSIT: {
      title: t('trips.detail.autoExpense.roadTransit'),
      category: 'road_transit',
    },
    IN_TRANSIT: { title: t('trips.detail.autoExpense.transit'), category: 'transit' },
    BORDER: { title: t('trips.detail.autoExpense.border'), category: 'road' },
    CUSTOMS: { title: t('trips.detail.autoExpense.customs'), category: 'customs' },
  }

function openAutomaticFeePopup(targetStatus: TripStatus) {
  if (!canManageExpenses.value || !trip.value) return
  if (targetStatus === 'SENT_FOR_LOADING') {
    // Phase 6: a company-owned truck's trip has no transporter, so no
    // commission is ever due (docs/superpowers/specs/2026-09-02-business-
    // corrections-6-phases-design.md).
    if (!trip.value.transporter) return
    automaticTransportTitle.value = t('trips.detail.autoExpense.transporterCommission')
    showTransportPaymentForm.value = true
    return
  }
  const expense = automaticExpenseByStatus[targetStatus]
  if (!expense) return
  automaticExpense.value = expense
  showExpenseForm.value = true
}

async function onChangeStatus() {
  if (!nextStatus.value) return
  const targetStatus = nextStatus.value as TripStatus
  changingStatus.value = true
  statusError.value = ''
  try {
    await postTripStatus(tripId.value, nextStatus.value, statusNotes.value)
    nextStatus.value = ''
    statusNotes.value = ''
    await Promise.all([load(), loadMargin()])
    await loadAllowedStatuses()
    openAutomaticFeePopup(targetStatus)
  } catch (e) {
    const data = (e as { response?: { data?: { detail?: string } } })?.response?.data
    statusError.value = translateApiError(data?.detail) || t('trips.detail.statusChangeError')
  } finally {
    changingStatus.value = false
  }
}

function badgeVariant(status: string) {
  if (status === 'COMPLETED' || status === 'DELIVERED') return 'livre' as const
  if (status === 'CANCELLED' || status === 'BLOCKED') return 'critique' as const
  if (status === 'ASSIGNED') return 'neutre' as const
  return 'ecart' as const
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString()
}

function expenseUnitPrice(expense: Expense) {
  const allocated = Number(tripAllocation(expense)?.allocated_amount ?? expense.amount)
  const quantity = Number(trip.value?.quantity_loaded ?? 0)
  return quantity ? allocated / quantity : 0
}

function tripExpenseLabel(expense: Expense) {
  if (expense.category === 'transit') return t('trips.detail.expenseLabels.transit')
  if (expense.category === 'road_transit') return t('trips.detail.expenseLabels.roadTransit')
  if (expense.category === 'road') return t('trips.detail.expenseLabels.border')
  return t(`expenseCategory.${expense.category}`)
}

function transportPaymentUnitPrice(payment: TransportPayment) {
  if (payment.unit_price_per_litre) return Number(payment.unit_price_per_litre)
  const quantity = Number(trip.value?.quantity_loaded ?? 0)
  return quantity ? Number(payment.base_amount) / quantity : 0
}

const cessionProofUrl = computed(() => trip.value?.cession_letter_detail?.documents[0]?.file ?? null)
</script>

<template>
  <div class="max-w-3xl space-y-6">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('trips.detail.title', { reference: trip?.reference ?? '' }) }}
      </h1>
      <Button variant="ghost" @click="router.push({ name: 'trips' })">
        {{ t('trips.detail.backToBoard') }}
      </Button>
    </div>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <template v-else-if="trip">
      <section class="border-ligne grid grid-cols-1 md:grid-cols-2 gap-4 rounded-xl border bg-white p-4 text-sm">
        <div>
          <span class="text-texte-2">{{ t('trips.detail.status') }}</span>
          <p class="mt-1">
            <Badge :variant="badgeVariant(trip.status)">{{ statusLabel(trip.status) }}</Badge>
          </p>
        </div>
        <div>
          <span class="text-texte-2">{{ t('trips.detail.truck') }}</span>
          <p class="text-texte font-medium">{{ trip.truck_detail?.internal_id }}</p>
        </div>
        <div>
          <span class="text-texte-2">{{ t('trips.detail.transporter') }}</span>
          <p class="text-texte font-medium">
            <RouterLink
              v-if="trip.transporter"
              class="underline decoration-dotted"
              :to="{ name: 'transporter-ledger', params: { id: trip.transporter } }"
            >
              {{ trip.transporter_detail?.name }}
            </RouterLink>
            <span v-else>{{ t('trips.detail.companyOwnedTruck') }}</span>
          </p>
        </div>
        <div>
          <span class="text-texte-2">{{ t('trips.detail.driver') }}</span>
          <p class="text-texte font-medium">{{ trip.driver_detail?.name ?? '—' }}</p>
        </div>
        <div>
          <span class="text-texte-2">{{ t('trips.detail.supplier') }}</span>
          <p class="text-texte font-medium">{{ trip.supplier_detail?.name }}</p>
        </div>
        <div>
          <span class="text-texte-2">{{ t('trips.detail.product') }}</span>
          <p class="text-texte font-medium">{{ trip.product_detail?.name }}</p>
        </div>
        <div>
          <span class="text-texte-2">{{ t('trips.detail.quantityLoaded') }}</span>
          <p>
            <MonoValue
              class="font-medium"
              align="left"
              :value="formatQuantity(trip.quantity_loaded)"
            />
          </p>
        </div>
        <div>
          <span class="text-texte-2">{{ t('trips.detail.loadingDate') }}</span>
          <p class="text-texte font-medium">{{ trip.loading_date }}</p>
        </div>
        <div>
          <span class="text-texte-2">{{ t('trips.detail.blReference') }}</span>
          <p><MonoValue :value="trip.bl_reference" align="left" class="font-medium" /></p>
        </div>
        <div>
          <span class="text-texte-2">{{ t('trips.detail.proof') }}</span>
          <p>
            <button
              v-if="cessionProofUrl"
              type="button"
              class="text-bitume underline"
              @click="previewUrl = cessionProofUrl"
            >
              {{ t('trips.detail.viewProof') }}
            </button>
            <span v-else class="text-texte-3">—</span>
          </p>
        </div>
        <div>
          <span class="text-texte-2">{{ t('trips.detail.client') }}</span>
          <p class="text-texte font-medium">
            {{
              trip.destination_type === 'COMPANY_STOCK'
                ? t('trips.detail.companyStock')
                : (trip.client_detail?.name ?? '—')
            }}
          </p>
          <Button
            v-if="canShowAssignCustomer"
            variant="ghost"
            class="mt-1"
            @click="showAssignCustomerForm = true"
          >
            {{ t('trips.detail.assignCustomer') }}
          </Button>
        </div>
        <div v-if="trip.customer_order">
          <span class="text-texte-2">{{ t('trips.detail.customerOrder') }}</span>
          <p>
            <RouterLink
              class="text-texte font-medium underline decoration-dotted"
              :to="{ name: 'customer-order-detail', params: { id: trip.customer_order } }"
            >
              #{{ trip.customer_order }}
            </RouterLink>
          </p>
        </div>
        <div v-if="trip.notes" class="col-span-2">
          <span class="text-texte-2">{{ t('trips.detail.notes') }}</span>
          <p class="text-texte font-medium">{{ trip.notes }}</p>
        </div>
      </section>

      <Card v-if="canChangeStatus" :title="t('trips.detail.changeStatus')">
        <div class="space-y-3">
          <p v-if="statusError" class="text-critique text-sm">{{ statusError }}</p>

          <div class="flex flex-wrap items-end gap-2">
            <div class="space-y-1">
              <label class="text-texte-2 text-sm font-medium" for="next_status">{{
                t('trips.detail.nextStatus')
              }}</label>
              <select
                id="next_status"
                v-model="nextStatus"
                class="border-ligne-forte h-11 rounded-lg border bg-white px-3 text-sm"
              >
                <option value="" disabled>{{ t('trips.detail.selectStatus') }}</option>
                <option v-for="s in visibleNextStatuses" :key="s" :value="s">
                  {{ statusLabel(s) }}
                </option>
              </select>
            </div>
            <div class="flex-1 space-y-1">
              <label class="text-texte-2 text-sm font-medium" for="status_notes">{{
                t('trips.detail.notes')
              }}</label>
              <input
                id="status_notes"
                v-model="statusNotes"
                class="border-ligne-forte h-11 w-full rounded-lg border bg-white px-3 text-sm"
              />
            </div>
            <Button :disabled="!nextStatus || changingStatus" @click="onChangeStatus">
              {{ changingStatus ? t('trips.detail.updating') : t('trips.detail.apply') }}
            </Button>
          </div>
        </div>
      </Card>

      <DeliveryControlForm
        v-if="trip.status === 'QUANTITY_CONTROL' && canChangeStatus"
        :trip-id="trip.id"
        :quantity-loaded="trip.quantity_loaded"
        @confirmed="onDeliveryConfirmed"
      />

      <section v-if="deliveryData" class="border-ligne space-y-4 rounded-xl border bg-white p-4">
        <h3 class="text-texte-2 text-sm font-semibold uppercase">{{ t('trips.detail.gauges') }}</h3>
        <div class="grid grid-cols-3 gap-4">
          <div>
            <p class="text-texte-3 text-xs uppercase">{{ t('trips.detail.loaded') }}</p>
            <MonoValue :value="formatQuantity(deliveryData.loaded_quantity)" align="left" />
          </div>
          <div>
            <p class="text-texte-3 text-xs uppercase">{{ t('trips.detail.delivered') }}</p>
            <MonoValue :value="formatQuantity(deliveryData.received_quantity)" align="left" />
          </div>
          <div>
            <p class="text-texte-3 text-xs uppercase">{{ t('trips.detail.gap') }}</p>
            <MonoValue
              :value="formatQuantity(deliveryData.loss_quantity)"
              align="left"
              :class="Number(deliveryData.chargeable_loss_quantity) > 0 ? 'text-critique' : ''"
            />
          </div>
        </div>
        <GaugeBar
          :value="deliveredPct"
          tone="livre"
          :label="t('trips.detail.deliveredOverLoaded')"
        />
        <GaugeBar
          :value="Math.min(100, (lossPct / 5) * 100)"
          :tone="lossSeverityTone(lossPct)"
          :label="t('trips.detail.gap')"
        />
      </section>

      <Card :title="t('trips.detail.history')">
        <ol class="border-ligne space-y-3 border-l ps-4">
          <li v-for="entry in history" :key="entry.id" class="relative text-sm">
            <span class="bg-texte-3 absolute top-1 -start-[21px] h-2 w-2 rounded-full" />
            <p class="text-texte font-medium">
              {{ statusLabel(entry.previous_status as TripStatus) }} →
              {{ statusLabel(entry.new_status as TripStatus) }}
            </p>
            <p class="text-texte-2 text-xs">
              {{ formatDateTime(entry.changed_at) }} · {{ entry.changed_by_detail?.email }}
            </p>
            <p v-if="entry.notes" class="text-texte-2">{{ entry.notes }}</p>
          </li>
          <li v-if="!history.length" class="text-texte-3">{{ t('trips.detail.noHistory') }}</li>
        </ol>
      </Card>

      <Card :title="t('trips.detail.expenses')">
        <div class="space-y-3">
          <p v-if="expensesError" class="text-critique text-sm">{{ expensesError }}</p>

          <ul class="divide-ligne divide-y">
            <li
              v-for="payment in transportPayments"
              :key="`transport-${payment.id}`"
              class="grid grid-cols-[1fr_auto] gap-3 py-2 text-sm"
            >
              <div>
                <p class="text-texte font-medium">
                  {{ t('trips.detail.transporterCommission') }}
                </p>
                <p class="text-texte-2 text-xs">
                  {{ formatUnitMoney(transportPaymentUnitPrice(payment)) }} ·
                  {{ formatQuantity(trip.quantity_loaded) }}
                </p>
              </div>
              <MonoValue :value="formatMoney(payment.base_amount)" align="left" />
            </li>
            <li
              v-for="expense in expenses"
              :key="expense.id"
              class="grid grid-cols-[1fr_auto] items-start gap-3 py-2 text-sm"
            >
              <div>
                <p class="text-texte font-medium">{{ tripExpenseLabel(expense) }}</p>
                <p class="text-texte-2 text-xs">
                  {{ expense.date }} ·
                  {{ formatUnitMoney(expenseUnitPrice(expense)) }} ·
                  {{ formatQuantity(trip.quantity_loaded) }}
                </p>
                <p v-if="expense.status === 'CANCELLED'" class="text-critique text-xs font-medium">
                  {{ t('trips.detail.expenseCancelled') }}
                </p>
              </div>
              <div class="flex flex-col items-end gap-1">
                <MonoValue
                  :value="formatMoney(tripAllocation(expense)?.allocated_amount ?? expense.amount)"
                  align="left"
                  :class="expense.status === 'CANCELLED' ? 'text-texte-3 line-through' : ''"
                />
                <button
                  v-if="
                    canCancelExpenses &&
                    (expense.status === 'PAID' || expense.status === 'PARTIALLY_PAID')
                  "
                  type="button"
                  class="text-critique text-xs hover:brightness-90 disabled:opacity-50"
                  :disabled="cancellingExpenseId === expense.id"
                  @click="onCancelExpense(expense)"
                >
                  {{ t('trips.detail.cancelExpense') }}
                </button>
              </div>
            </li>
            <li
              v-if="!expenses.length && !transportPayments.length"
              class="text-texte-3 py-2 text-sm"
            >
              {{ t('trips.detail.noExpenses') }}
            </li>
          </ul>

          <div class="flex gap-2">
            <Button
              v-if="canManageExpenses"
              variant="ghost"
              @click=";(automaticExpense = null), (showExpenseForm = true)"
            >
              {{ t('trips.detail.addExpense') }}
            </Button>
            <Button
              v-if="canManageExpenses && trip.transporter"
              variant="ghost"
              @click=";(automaticTransportTitle = null), (showTransportPaymentForm = true)"
            >
              {{ t('trips.detail.addTransportFee') }}
            </Button>
          </div>
        </div>
      </Card>

      <Card :title="t('trips.detail.margin')">
        <p v-if="marginError" class="text-critique text-sm">{{ marginError }}</p>
        <p v-else-if="!margin?.available" class="text-texte-3 text-sm">
          {{ t('trips.detail.marginUnavailable') }}
        </p>
        <dl v-else class="divide-ligne divide-y text-sm">
          <div class="flex items-center justify-between py-2">
            <dt class="text-texte-2">{{ t('trips.detail.quantityLoaded') }}</dt>
            <dd><MonoValue :value="formatQuantity(margin.quantity_loaded)" align="left" /></dd>
          </div>
          <div class="flex items-center justify-between py-2">
            <dt class="text-texte-2">{{ t('trips.detail.quantityInvoiced') }}</dt>
            <dd><MonoValue :value="formatQuantity(margin.quantity_invoiced)" align="left" /></dd>
          </div>
          <div class="flex items-center justify-between py-2">
            <dt class="text-texte-2">{{ t('trips.detail.revenue') }}</dt>
            <dd><MonoValue :value="formatMoney(margin.revenue)" align="left" /></dd>
          </div>
          <div class="flex items-center justify-between py-2">
            <dt class="text-texte-2">{{ t('trips.detail.transporterLossQuantity') }}</dt>
            <dd><MonoValue :value="formatQuantity(margin.transporter_loss_quantity)" align="left" /></dd>
          </div>
          <div class="flex items-center justify-between py-2">
            <dt class="text-texte-2">{{ t('trips.detail.transporterLossIndemnity') }}</dt>
            <dd><MonoValue :value="formatMoney(margin.transporter_loss_indemnity)" align="left" /></dd>
          </div>
          <div class="flex items-center justify-between py-2">
            <dt class="text-texte-2">{{ t('trips.detail.fuelPurchaseCost') }}</dt>
            <dd>
              <MonoValue :value="`-${formatMoney(margin.fuel_purchase_cost)}`" align="left" />
            </dd>
          </div>
          <div class="flex items-center justify-between py-2">
            <dt class="text-texte-2">{{ t('trips.detail.transportCost') }}</dt>
            <dd>
              <MonoValue :value="`-${formatMoney(margin.transport_cost)}`" align="left" />
            </dd>
          </div>
          <div
            v-for="(amount, category) in margin.expenses_by_category"
            :key="category"
            class="flex items-center justify-between py-2"
          >
            <dt class="text-texte-2">{{ t(`expenseCategory.${category}`) }}</dt>
            <dd><MonoValue :value="`-${formatMoney(amount)}`" align="left" /></dd>
          </div>
          <div class="flex items-center justify-between py-2">
            <dt class="text-texte-2">{{ t('trips.detail.unitCost') }}</dt>
            <dd><MonoValue :value="formatUnitMoney(margin.unit_cost)" align="left" /></dd>
          </div>
          <div class="flex items-center justify-between py-2">
            <dt class="text-texte-2">{{ t('trips.detail.realTotalCost') }}</dt>
            <dd><MonoValue :value="formatMoney(margin.real_total_cost)" align="left" /></dd>
          </div>
          <div class="flex items-center justify-between py-2">
            <dt class="text-texte-2">{{ t('trips.detail.unitProfit') }}</dt>
            <dd>
              <MonoValue
                :class="Number(margin.unit_profit) < 0 ? 'text-critique' : 'text-livre'"
                :value="formatUnitMoney(margin.unit_profit)"
                align="left"
              />
            </dd>
          </div>
          <div class="flex items-center justify-between py-3">
            <dt class="text-texte font-semibold uppercase">{{ t('trips.detail.netMargin') }}</dt>
            <dd>
              <MonoValue
                class="text-base font-semibold"
                :class="Number(margin.margin) < 0 ? 'text-critique' : 'text-livre'"
                :value="formatMoney(margin.margin)"
                align="left"
              />
            </dd>
          </div>
        </dl>
      </Card>

      <div
        v-if="showExpenseForm"
        class="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4"
      >
        <div class="max-h-[90vh] w-full max-w-lg overflow-y-auto">
          <ExpenseForm
            :preset-allocation="{ kind: 'trip', objectId: trip.id, label: trip.reference }"
            :title="automaticExpense?.title"
            :initial-category="automaticExpense?.category"
            :initial-calculation-method="automaticExpense ? 'PER_LITRE' : undefined"
            :per-litre-quantity="trip.quantity_loaded"
            @success="onExpenseSaved"
            @cancel=";(showExpenseForm = false), (automaticExpense = null)"
          />
        </div>
      </div>

      <div
        v-if="showTransportPaymentForm"
        class="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4"
      >
        <div class="max-h-[90vh] w-full max-w-lg overflow-y-auto">
          <TransportPaymentForm
            :title="automaticTransportTitle ?? undefined"
            :trip-id="trip.id"
            :trip-reference="trip.reference"
            :transporter-id="trip.transporter!"
            :transporter-name="trip.transporter_detail?.name ?? ''"
            :quantity-loaded="trip.quantity_loaded"
            @success="onTransportPaymentSaved"
            @cancel=";(showTransportPaymentForm = false), (automaticTransportTitle = null)"
          />
        </div>
      </div>

      <div
        v-if="showAssignCustomerForm"
        class="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4"
      >
        <div class="max-h-[90vh] w-full max-w-lg overflow-y-auto">
          <AssignCustomerForm
            :trip-id="trip.id"
            :trip-reference="trip.reference"
            @success="onCustomerAssigned"
            @cancel="showAssignCustomerForm = false"
          />
        </div>
      </div>

      <Modal
        v-if="previewUrl"
        :title="t('trips.detail.proof')"
        max-width="max-w-3xl"
        @close="previewUrl = null"
      >
        <img :src="previewUrl" class="max-h-[80vh] w-full rounded-lg object-contain" />
        <div class="mt-4 flex justify-end">
          <Button variant="ghost" @click="previewUrl = null">{{ t('common.close') }}</Button>
        </div>
      </Modal>
    </template>
  </div>
</template>
