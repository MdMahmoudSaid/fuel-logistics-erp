<script setup lang="ts">
// "Frais & étapes du trajet" (client request 2026-11-09): one row per status
// that carries a fee, in workflow order. The row name IS the status name.
// Every row is editable in place - pick the calculation, type the amount, press
// Enter (or "Enregistrer"): two actions per fee, no popup. Saving a fee moves
// the trip to that row's status when it is ahead of the current one, so the
// last fee entered is the trip's current status. Fees can be entered one at a
// time, days apart; a saved fee stays editable while it is unpaid.
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppAlert from '@/components/ui/AppAlert.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import {
  expenseResource,
  fetchAllocatableTypes,
  transportPaymentResource,
} from '@/modules/finance/api'
import type { Expense, ExpenseCategory, TransportPayment } from '@/modules/finance/types'
import { translateApiError } from '@/i18n/apiErrors'
import { formatMoney, formatQuantity, formatUnitMoney } from '@/utils/currency'
import { useTripStatusLabel } from './tripStatusLabels'
import type { Trip, TripStatus } from './types'

const props = defineProps<{
  trip: Trip
  expenses: Expense[]
  transportPayments: TransportPayment[]
  canManage: boolean
}>()
const emit = defineEmits<{
  recorded: [status: TripStatus]
}>()

const { t } = useI18n()
const statusLabel = useTripStatusLabel()

type Method = 'PER_LITRE' | 'PER_TRUCK'

interface Row {
  status: TripStatus
  category: ExpenseCategory | null // null = transporter commission
}

const FEE_ROWS: Row[] = [
  { status: 'LOADING', category: 'loading' },
  { status: 'ROAD_TRANSIT', category: 'road_transit' },
  { status: 'IN_TRANSIT', category: 'transit' },
  { status: 'BORDER', category: 'road' },
  { status: 'CUSTOMS', category: 'customs' },
]

const hasCommissionRow = computed(
  () => !!props.trip.transporter && !props.trip.transporter_detail?.is_internal,
)
const rows = computed<Row[]>(() =>
  hasCommissionRow.value ? [{ status: 'SENT_FOR_LOADING', category: null }, ...FEE_ROWS] : FEE_ROWS,
)
const quantity = computed(() => Number(props.trip.quantity_loaded) || 0)

function expenseFor(row: Row): Expense | undefined {
  return props.expenses.find((e) => e.category === row.category && e.status !== 'CANCELLED')
}
function commission(): TransportPayment | undefined {
  return props.transportPayments.find((p) => p.status !== 'CANCELLED')
}
function allocatedTotal(expense: Expense): number {
  const slice = expense.allocations_detail.find(
    (a) => a.content_type_name === 'trip' && a.object_id === props.trip.id,
  )
  return Number(slice?.allocated_amount ?? expense.amount)
}

// What is saved for a row (null = nothing yet).
interface Saved {
  method: string
  amount: string
  total: number
  paid: boolean
}
function saved(row: Row): Saved | null {
  if (row.category === null) {
    const p = commission()
    if (!p) return null
    return {
      method: p.calculation_method,
      amount: p.unit_price_per_litre ?? p.base_amount,
      total: Number(p.base_amount),
      paid: !p.can_modify,
    }
  }
  const e = expenseFor(row)
  if (!e) return null
  return {
    method: e.calculation_method,
    amount: e.amount,
    total: allocatedTotal(e),
    paid: e.status !== 'UNPAID',
  }
}

// --- in-place edits ---------------------------------------------------------
const edits = reactive<Record<string, { method?: Method; amount?: string }>>({})
const savingStatus = ref<TripStatus | null>(null)
const error = ref('')
const allocatableTypes = ref<Record<string, number>>({})

onMounted(async () => {
  try {
    allocatableTypes.value = (await fetchAllocatableTypes()) as Record<string, number>
  } catch {
    allocatableTypes.value = {}
  }
})

function methodOf(row: Row): Method {
  const edited = edits[row.status]?.method
  if (edited) return edited
  return isFlat(saved(row)?.method) ? 'PER_TRUCK' : 'PER_LITRE'
}
// A commission stores a flat amount as FIXED, an expense as PER_TRUCK.
function isFlat(method: string | undefined): boolean {
  return method === 'PER_TRUCK' || method === 'FIXED'
}
function amountOf(row: Row): string {
  const edited = edits[row.status]?.amount
  return edited !== undefined ? edited : (saved(row)?.amount ?? '')
}
function setMethod(row: Row, value: Method) {
  edits[row.status] = { ...edits[row.status], method: value }
}
function setAmount(row: Row, value: string) {
  edits[row.status] = { ...edits[row.status], amount: value }
}

function totalOf(row: Row): number {
  const amount = Number(amountOf(row)) || 0
  return methodOf(row) === 'PER_LITRE' ? amount * quantity.value : amount
}
function unitOf(row: Row): number {
  return quantity.value ? totalOf(row) / quantity.value : 0
}

function isDirty(row: Row): boolean {
  const s = saved(row)
  const amount = Number(amountOf(row)) || 0
  if (!s) return amount > 0
  const sameMethod = methodOf(row) === (isFlat(s.method) ? 'PER_TRUCK' : 'PER_LITRE')
  return amount > 0 && !(sameMethod && Number(s.amount) === amount)
}
function isEditable(row: Row): boolean {
  return props.canManage && !saved(row)?.paid
}

// Transporter commission = a TransportPayment (its own debt), not an Expense.
// PER_LITRE: the backend derives base_amount from quantity_loaded x rate.
async function saveCommission(row: Row) {
  const amount = String(amountOf(row))
  const payload =
    methodOf(row) === 'PER_LITRE'
      ? { calculation_method: 'PER_LITRE' as const, unit_price_per_litre: amount }
      : { calculation_method: 'FIXED' as const, base_amount: amount, unit_price_per_litre: null }
  const existing = commission()
  if (existing) await transportPaymentResource.update(existing.id, payload)
  else
    await transportPaymentResource.create({
      trip: props.trip.id,
      transporter: props.trip.transporter!,
      ...payload,
    })
}

async function save(row: Row) {
  if (!isDirty(row)) return
  savingStatus.value = row.status
  error.value = ''
  try {
    if (row.category === null) {
      await saveCommission(row)
      delete edits[row.status]
      emit('recorded', row.status)
      return
    }
    const existing = expenseFor(row)
    const payload = {
      category: row.category,
      amount: String(amountOf(row)),
      calculation_method: methodOf(row),
      date: existing?.date ?? new Date().toISOString().slice(0, 10),
      notes: existing?.notes ?? '',
      allocations: [
        {
          content_type: allocatableTypes.value.trip ?? null,
          object_id: props.trip.id,
          allocated_amount: String(totalOf(row)),
        },
      ],
    }
    if (existing) await expenseResource.update(existing.id, payload)
    else await expenseResource.create(payload)
    delete edits[row.status]
    emit('recorded', row.status)
  } catch (e) {
    const data = (e as { response?: { data?: Record<string, unknown> } })?.response?.data
    const detail = typeof data?.detail === 'string' ? data.detail : undefined
    const first = data
      ? Object.values(data)
          .flat()
          .find((v): v is string => typeof v === 'string')
      : undefined
    error.value = translateApiError(detail) || first || t('finance.expense.saveError')
  } finally {
    savingStatus.value = null
  }
}

const COLS = 'md:grid-cols-[minmax(0,1.4fr)_8rem_minmax(0,1fr)_minmax(0,1fr)_6.5rem]'
</script>

<template>
  <div class="space-y-3" data-test="trip-fee-table">
    <p class="text-texte-2 text-sm">{{ t('trips.feeTable.hint') }}</p>
    <AppAlert v-if="error" :message="error" />

    <div class="border-ligne overflow-hidden rounded-xl border bg-white">
      <div
        class="bg-sable text-texte-2 hidden gap-x-3 px-3 py-2 text-xs font-medium uppercase md:grid"
        :class="COLS"
      >
        <span>{{ t('trips.feeTable.stage') }}</span>
        <span>{{ t('trips.feeTable.method') }}</span>
        <span>{{ t('trips.feeTable.amount') }}</span>
        <span class="text-end">{{ t('trips.feeTable.total') }}</span>
        <span />
      </div>

      <div class="divide-ligne divide-y">
        <div
          v-for="row in rows"
          :key="row.status"
          :data-test="`fee-row-${row.status}`"
          class="grid grid-cols-2 items-center gap-x-3 gap-y-2 px-3 py-3"
          :class="[COLS, trip.status === row.status ? 'bg-ecart-tint/40' : '']"
        >
          <!-- stage + state -->
          <div class="col-span-2 min-w-0 md:col-span-1">
            <p class="text-texte font-medium">
              {{
                row.category === null ? t('trips.feeTable.commissionHint') : statusLabel(row.status)
              }}
            </p>
            <p v-if="row.category === null" class="text-texte-3 text-xs">
              {{ statusLabel(row.status) }}
            </p>
            <div class="mt-1 flex flex-wrap items-center gap-1.5">
              <Badge v-if="saved(row)" :variant="saved(row)!.paid ? 'livre' : 'transit'">
                {{ saved(row)!.paid ? t('trips.feeTable.paid') : t('trips.feeTable.entered') }}
              </Badge>
              <Badge v-else variant="neutre">{{ t('trips.feeTable.toEnter') }}</Badge>
              <span v-if="trip.status === row.status" class="text-ecart-texte text-xs font-medium">
                {{ t('trips.feeTable.currentStatus') }}
              </span>
            </div>
          </div>

          <!-- editable fee -->
          <template v-if="isEditable(row)">
            <select
              :value="methodOf(row)"
              class="border-ligne-forte h-10 w-full rounded-lg border bg-white px-2 text-sm"
              :aria-label="t('trips.feeTable.method')"
              :data-test="`fee-method-${row.status}`"
              @change="setMethod(row, ($event.target as HTMLSelectElement).value as Method)"
            >
              <option value="PER_LITRE">{{ t('expenseCalcMethod.PER_LITRE') }}</option>
              <option value="PER_TRUCK">{{ t('expenseCalcMethod.PER_TRUCK') }}</option>
            </select>
            <div class="relative">
              <input
                :value="amountOf(row)"
                type="number"
                min="0"
                step="any"
                inputmode="decimal"
                class="border-ligne-forte h-10 w-full rounded-lg border bg-white ps-2 pe-14 text-end text-sm"
                :aria-label="t('trips.feeTable.amount')"
                :data-test="`fee-amount-${row.status}`"
                @input="setAmount(row, ($event.target as HTMLInputElement).value)"
                @keydown.enter.prevent="save(row)"
              />
              <span
                class="text-texte-3 pointer-events-none absolute inset-y-0 end-2 flex items-center text-xs"
              >
                {{ methodOf(row) === 'PER_LITRE' ? 'XOF/L' : 'XOF' }}
              </span>
            </div>
            <div class="text-end">
              <MonoValue v-if="totalOf(row) > 0" :value="formatMoney(totalOf(row))" />
              <span v-else class="text-texte-3">—</span>
              <p v-if="totalOf(row) > 0" class="text-texte-3 text-xs">
                {{ formatUnitMoney(unitOf(row)) }} · {{ formatQuantity(trip.quantity_loaded) }}
              </p>
            </div>
            <div class="text-end">
              <Button
                v-if="isDirty(row)"
                class="!h-10 !px-3"
                :disabled="savingStatus === row.status"
                :data-test="`fee-save-${row.status}`"
                @click="save(row)"
              >
                {{
                  savingStatus === row.status
                    ? t('trips.feeTable.saving')
                    : t('trips.feeTable.save')
                }}
              </Button>
              <span v-else-if="saved(row)" class="text-livre text-lg" aria-hidden="true">✓</span>
            </div>
          </template>

          <!-- read only (paid, or no right to edit) -->
          <template v-else>
            <p class="text-texte-2 text-sm">
              {{ saved(row) ? t(`expenseCalcMethod.${saved(row)!.method}`) : '—' }}
            </p>
            <div class="text-end">
              <MonoValue
                v-if="saved(row)"
                :value="formatUnitMoney(saved(row)!.total / (quantity || 1))"
              />
              <span v-else class="text-texte-3">—</span>
            </div>
            <div class="text-end">
              <MonoValue v-if="saved(row)" :value="formatMoney(saved(row)!.total)" />
              <span v-else class="text-texte-3">—</span>
            </div>
            <div />
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
