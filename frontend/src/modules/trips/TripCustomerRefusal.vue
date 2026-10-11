<script setup lang="ts">
// "Le client refuse le trajet" (client request 2026-10-11). Two outcomes:
// back to the company stock (only before delivery) or another customer -
// once delivered, the sale and invoice follow the trip at the new
// customer's price, and the former customer keeps neither the trip nor any
// invoice for it. The impact is previewed (GET customer-refusal-preview)
// before the operator confirms; TripCustomerRefusalService does the rest.
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppAlert from '@/components/ui/AppAlert.vue'
import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import Modal from '@/components/ui/Modal.vue'
import MonoValue from '@/components/ui/MonoValue.vue'
import SearchableSelect from '@/components/ui/SearchableSelect.vue'
import { confirmDialog } from '@/composables/useConfirmDialog'
import { translateApiError } from '@/i18n/apiErrors'
import { formatMoney, formatQuantity } from '@/utils/currency'
import {
  fetchCustomerRefusalPreview,
  listAllCustomers,
  refuseTripCustomer,
  type CustomerRefusalAction,
  type CustomerRefusalPreview,
} from './api'
import { useTripStatusLabel } from './tripStatusLabels'
import type { Trip } from './types'

const props = defineProps<{
  trip: Trip
  customerName: string
  // A sale exists: only "another customer" is possible.
  delivered: boolean
}>()
const emit = defineEmits<{ done: []; close: [] }>()

const { t } = useI18n()
const statusLabel = useTripStatusLabel()

const action = ref<CustomerRefusalAction>(props.delivered ? 'CHANGE_CUSTOMER' : 'RETURN_TO_STOCK')
const customers = ref<{ id: number; name: string; is_active?: boolean }[]>([])
const customerId = ref('')
const unitPrice = ref('')
const reason = ref('')
const preview = ref<CustomerRefusalPreview | null>(null)
const loadingPreview = ref(false)
const saving = ref(false)
const error = ref('')

// The refusing customer: the trip's direct client, else (order-only trip)
// the one the preview resolves.
const refusingId = computed(() => props.trip.client ?? preview.value?.old_customer.id ?? null)
const refusingName = computed(() => preview.value?.old_customer.name ?? props.customerName)

const customerOptions = computed(() =>
  customers.value
    .filter((c) => c.is_active !== false && c.id !== refusingId.value)
    .map((c) => ({ value: String(c.id), label: c.name })),
)

onMounted(async () => {
  try {
    customers.value = await listAllCustomers()
  } catch {
    error.value = t('trips.customerRefusal.loadError')
  }
})

function apiDetail(e: unknown) {
  return (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
}

let previewSeq = 0
async function loadPreview() {
  const seq = ++previewSeq
  error.value = ''
  if (action.value === 'CHANGE_CUSTOMER' && !customerId.value) {
    preview.value = null
    return
  }
  loadingPreview.value = true
  try {
    const result = await fetchCustomerRefusalPreview(props.trip.id, {
      action: action.value,
      customer: customerId.value ? Number(customerId.value) : undefined,
      unit_selling_price: unitPrice.value || undefined,
    })
    if (seq !== previewSeq) return
    preview.value = result
  } catch (e) {
    if (seq !== previewSeq) return
    preview.value = null
    error.value = translateApiError(apiDetail(e)) || t('trips.customerRefusal.previewError')
  } finally {
    if (seq === previewSeq) loadingPreview.value = false
  }
}

watch(action, () => {
  preview.value = null
  loadPreview()
})

// A new customer brings his own last price: start from it (or from the
// current price when he has none on file).
let settingPrice = false
watch(customerId, async () => {
  settingPrice = true
  unitPrice.value = ''
  await loadPreview()
  if (preview.value?.delivered) {
    unitPrice.value = preview.value.unit_price ?? ''
  }
  setTimeout(() => (settingPrice = false))
})

let priceTimer: ReturnType<typeof setTimeout> | undefined
watch(unitPrice, () => {
  if (settingPrice || !customerId.value) return
  clearTimeout(priceTimer)
  priceTimer = setTimeout(loadPreview, 350)
})

onMounted(loadPreview)

const priceValid = computed(
  () =>
    !props.delivered ||
    action.value !== 'CHANGE_CUSTOMER' ||
    (unitPrice.value !== '' && Number(unitPrice.value) >= 0),
)
const canSubmit = computed(
  () =>
    !!preview.value &&
    !loadingPreview.value &&
    reason.value.trim() !== '' &&
    priceValid.value &&
    !saving.value,
)

async function onSubmit() {
  if (!preview.value || !canSubmit.value) return
  const message =
    action.value === 'RETURN_TO_STOCK'
      ? t('trips.customerRefusal.confirmStock', {
          trip: props.trip.reference,
          name: refusingName.value,
        })
      : t('trips.customerRefusal.confirmChange', {
          trip: props.trip.reference,
          from: refusingName.value,
          to: preview.value.new_customer?.name ?? '',
        })
  if (!(await confirmDialog(message))) return
  saving.value = true
  error.value = ''
  try {
    await refuseTripCustomer(props.trip.id, {
      action: action.value,
      reason: reason.value,
      customer: action.value === 'CHANGE_CUSTOMER' ? Number(customerId.value) : undefined,
      unit_selling_price:
        action.value === 'CHANGE_CUSTOMER' && props.delivered ? unitPrice.value : undefined,
    })
    emit('done')
  } catch (e) {
    error.value = translateApiError(apiDetail(e)) || t('trips.customerRefusal.saveError')
  } finally {
    saving.value = false
  }
}

function balanceClass(value: string) {
  const n = Number(value)
  if (n > 0) return 'text-critique'
  if (n < 0) return 'text-livre'
  return 'text-texte'
}

const choices = computed(() => [
  {
    value: 'RETURN_TO_STOCK' as const,
    icon: 'package' as const,
    title: t('trips.customerRefusal.stockTitle'),
    text: props.delivered
      ? t('trips.customerRefusal.stockDisabled')
      : t('trips.customerRefusal.stockText'),
    disabled: props.delivered,
  },
  {
    value: 'CHANGE_CUSTOMER' as const,
    icon: 'users' as const,
    title: t('trips.customerRefusal.changeTitle'),
    text: props.delivered
      ? t('trips.customerRefusal.changeTextDelivered')
      : t('trips.customerRefusal.changeText'),
    disabled: false,
  },
])
</script>

<template>
  <Modal :title="t('trips.customerRefusal.title')" max-width="max-w-2xl" @close="emit('close')">
    <div class="space-y-5" data-test="customer-refusal">
      <div
        class="border-ligne bg-sable flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border px-3 py-2 text-sm"
      >
        <span class="text-texte font-semibold">{{ trip.reference }}</span>
        <span class="text-texte-2">
          {{ t('trips.customerRefusal.currentCustomer') }}
          <strong class="text-texte">{{ refusingName }}</strong>
        </span>
        <span class="text-texte-2">{{ statusLabel(trip.status) }}</span>
      </div>

      <AppAlert v-if="error" :message="error" />

      <fieldset class="space-y-2">
        <legend class="text-texte-2 mb-2 text-sm font-medium">
          {{ t('trips.customerRefusal.question') }}
        </legend>
        <div class="grid gap-3 sm:grid-cols-2">
          <label
            v-for="choice in choices"
            :key="choice.value"
            class="relative flex gap-3 rounded-xl border-2 p-3 transition-colors"
            :class="[
              choice.disabled
                ? 'border-ligne bg-sable cursor-not-allowed opacity-60'
                : 'cursor-pointer bg-white',
              !choice.disabled && action === choice.value
                ? 'border-bitume'
                : !choice.disabled
                  ? 'border-ligne hover:border-ligne-forte'
                  : '',
            ]"
            :data-test="`refusal-choice-${choice.value}`"
          >
            <input
              v-model="action"
              type="radio"
              class="sr-only"
              :value="choice.value"
              :disabled="choice.disabled"
            />
            <span
              class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
              :class="
                action === choice.value && !choice.disabled
                  ? 'bg-bitume text-white'
                  : 'bg-sable text-texte-2'
              "
            >
              <Icon :name="choice.icon" :size="18" />
            </span>
            <span class="space-y-0.5">
              <span class="text-texte block text-sm font-semibold">{{ choice.title }}</span>
              <span class="text-texte-2 block text-xs leading-snug">{{ choice.text }}</span>
            </span>
          </label>
        </div>
      </fieldset>

      <template v-if="action === 'CHANGE_CUSTOMER'">
        <div class="grid gap-3" :class="delivered ? 'sm:grid-cols-[2fr_1fr]' : ''">
          <label class="block space-y-1">
            <span class="text-texte-2 text-sm font-medium">
              {{ t('trips.customerRefusal.newCustomer') }}
            </span>
            <SearchableSelect
              v-model="customerId"
              :options="customerOptions"
              :placeholder="t('trips.customerRefusal.selectCustomer')"
            />
          </label>
          <label v-if="delivered" class="block space-y-1">
            <span class="text-texte-2 text-sm font-medium">
              {{ t('trips.customerRefusal.unitPrice') }}
            </span>
            <input
              v-model="unitPrice"
              data-test="refusal-unit-price"
              type="number"
              step="0.0001"
              min="0"
              :disabled="!customerId"
              class="border-ligne-forte h-11 w-full rounded-lg border bg-white px-3 text-sm disabled:opacity-50"
            />
          </label>
        </div>
        <p v-if="preview?.delivered && preview.new_customer" class="text-texte-3 -mt-2 text-xs">
          {{
            t('trips.customerRefusal.priceHint', {
              current: preview.current_unit_price,
              suggested: preview.suggested_unit_price ?? '—',
              name: preview.new_customer.name,
            })
          }}
        </p>
      </template>

      <p v-if="loadingPreview" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

      <!-- Impact: back to stock -->
      <div
        v-if="preview && action === 'RETURN_TO_STOCK'"
        class="border-ligne rounded-lg border bg-white p-3 text-sm"
        data-test="refusal-preview"
      >
        <ul class="text-texte-2 list-disc space-y-1 ps-5">
          <li>{{ t('trips.customerRefusal.stockEffect', { name: refusingName }) }}</li>
          <li v-if="preview.status_after !== trip.status">
            {{
              t('trips.customerRefusal.statusEffect', {
                from: statusLabel(trip.status),
                to: statusLabel(preview.status_after),
              })
            }}
          </li>
          <li v-else>{{ t('trips.customerRefusal.routeEffect') }}</li>
          <li>{{ t('trips.customerRefusal.noInvoiceEffect') }}</li>
        </ul>
      </div>

      <!-- Impact: another customer -->
      <div
        v-if="preview && action === 'CHANGE_CUSTOMER' && preview.new_customer"
        class="space-y-3"
        data-test="refusal-preview"
      >
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-stretch">
          <div class="border-ligne rounded-lg border bg-white p-3">
            <p class="text-texte-3 text-xs font-medium uppercase">
              {{ t('trips.customerRefusal.from') }}
            </p>
            <p class="text-texte mt-0.5 font-semibold">{{ preview.old_customer.name }}</p>
            <dl v-if="preview.delivered" class="mt-2 space-y-1 text-sm">
              <div class="flex justify-between gap-3">
                <dt class="text-texte-2">{{ t('trips.customerRefusal.balanceBefore') }}</dt>
                <dd :class="balanceClass(preview.old_customer.balance_before)">
                  <MonoValue :value="formatMoney(preview.old_customer.balance_before)" />
                </dd>
              </div>
              <div class="flex justify-between gap-3">
                <dt class="text-texte-2">{{ t('trips.customerRefusal.balanceAfter') }}</dt>
                <dd class="font-semibold" :class="balanceClass(preview.old_customer.balance_after)">
                  <MonoValue :value="formatMoney(preview.old_customer.balance_after)" />
                </dd>
              </div>
            </dl>
          </div>

          <div class="flex flex-col items-center justify-center gap-1 px-2 text-center">
            <span class="text-texte-3 text-xs">{{ trip.reference }}</span>
            <template v-if="preview.delivered">
              <span class="text-texte-3 text-xs">
                {{ formatQuantity(preview.quantity ?? 0) }} × {{ preview.unit_price }}
              </span>
              <MonoValue
                class="text-texte font-semibold"
                :value="formatMoney(preview.new_amount)"
              />
            </template>
            <span class="text-texte-2 text-xl leading-none rtl:rotate-180" aria-hidden="true"
              >→</span
            >
          </div>

          <div class="border-bitume rounded-lg border-2 bg-white p-3">
            <p class="text-texte-3 text-xs font-medium uppercase">
              {{ t('trips.customerRefusal.to') }}
            </p>
            <p class="text-texte mt-0.5 font-semibold">{{ preview.new_customer.name }}</p>
            <dl v-if="preview.delivered" class="mt-2 space-y-1 text-sm">
              <div class="flex justify-between gap-3">
                <dt class="text-texte-2">{{ t('trips.customerRefusal.balanceBefore') }}</dt>
                <dd :class="balanceClass(preview.new_customer.balance_before)">
                  <MonoValue :value="formatMoney(preview.new_customer.balance_before)" />
                </dd>
              </div>
              <div class="flex justify-between gap-3">
                <dt class="text-texte-2">{{ t('trips.customerRefusal.balanceAfter') }}</dt>
                <dd class="font-semibold" :class="balanceClass(preview.new_customer.balance_after)">
                  <MonoValue :value="formatMoney(preview.new_customer.balance_after)" />
                </dd>
              </div>
            </dl>
          </div>
        </div>

        <ul class="text-texte-2 list-disc space-y-1 ps-5 text-sm">
          <template v-if="preview.delivered">
            <li v-if="preview.grouped">
              {{ t('trips.customerRefusal.groupedEffect', { invoice: preview.invoice_number }) }}
            </li>
            <li v-else-if="preview.invoice_number">
              {{
                t('trips.customerRefusal.invoiceEffect', {
                  invoice: preview.invoice_number,
                  name: preview.new_customer.name,
                })
              }}
            </li>
            <li v-else>{{ t('trips.customerRefusal.waitingGroupEffect') }}</li>
            <li v-if="Number(preview.released_payments) > 0" data-test="released-payments">
              {{
                t('trips.customerRefusal.released', {
                  amount: formatMoney(preview.released_payments),
                  name: preview.old_customer.name,
                })
              }}
            </li>
            <li v-if="Number(preview.new_customer.credit_applied) > 0">
              {{
                t('trips.customerRefusal.creditApplied', {
                  amount: formatMoney(preview.new_customer.credit_applied),
                  name: preview.new_customer.name,
                })
              }}
            </li>
          </template>
          <li v-else>
            {{
              t('trips.customerRefusal.beforeDeliveryEffect', { name: preview.new_customer.name })
            }}
          </li>
          <li>{{ t('trips.customerRefusal.oldNothing', { name: preview.old_customer.name }) }}</li>
        </ul>
      </div>

      <label class="block space-y-1">
        <span class="text-texte-2 text-sm font-medium">{{
          t('trips.customerRefusal.reason')
        }}</span>
        <textarea
          v-model="reason"
          data-test="refusal-reason"
          rows="2"
          :placeholder="t('trips.customerRefusal.reasonPlaceholder')"
          class="border-ligne-forte w-full rounded-lg border bg-white px-3 py-2 text-sm"
        />
      </label>
      <p class="text-texte-3 text-xs">{{ t('trips.customerRefusal.audit') }}</p>

      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('close')">
          {{ t('common.cancel') }}
        </Button>
        <Button
          type="button"
          data-test="refusal-submit"
          :disabled="!canSubmit"
          :loading="saving"
          @click="onSubmit"
        >
          {{
            action === 'RETURN_TO_STOCK'
              ? t('trips.customerRefusal.submitStock')
              : t('trips.customerRefusal.submitChange')
          }}
        </Button>
      </div>
    </div>
  </Modal>
</template>
