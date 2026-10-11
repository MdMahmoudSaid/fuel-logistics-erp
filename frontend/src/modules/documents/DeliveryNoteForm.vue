<script setup lang="ts">
// Delivery note (spec 2026-10-11 documents-commerciaux §4): pick a customer,
// tick their delivered trips - each fills a line - then adjust freely.
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import AppAlert from '@/components/ui/AppAlert.vue'
import Button from '@/components/ui/Button.vue'
import DocumentFormHeader from './DocumentFormHeader.vue'
import LinesTable from './LinesTable.vue'
import type { LineColumn } from './LinesTable.vue'
import { formatQuantity } from '@/utils/currency'
import { fetchDeliverableTrips, listAll } from './api'
import type { DeliverableTrip, DeliveryNote, DeliveryNoteLine } from './types'
import { CARD_CLASS, FIELD_CLASS, LABEL_CLASS, today, useDocumentForm } from './useDocumentForm'

interface CustomerOption {
  id: number
  name: string
  address?: string
}

const { t } = useI18n()
const { current, saving, busy, error, load, save, pdf, print, back } =
  useDocumentForm<DeliveryNote>('delivery')

const customers = ref<CustomerOption[]>([])
const trips = ref<DeliverableTrip[]>([])
const form = ref({
  customer: '',
  date: today(),
  place: '',
  delivery_address: '',
  notes: '',
  lines: [] as Record<string, unknown>[],
})

const COLUMNS: LineColumn[] = [
  { field: 'designation', labelKey: 'documents.lines.designation' },
  { field: 'quantity', labelKey: 'documents.lines.quantity', type: 'number' },
  { field: 'tanker', labelKey: 'documents.lines.tanker' },
  { field: 'tractor', labelKey: 'documents.lines.tractor' },
  { field: 'missing', labelKey: 'documents.lines.missing', type: 'number' },
  { field: 'observation', labelKey: 'documents.lines.observation' },
]
const newLine = (): Record<string, unknown> => ({
  trip: null,
  designation: 'GASOIL',
  quantity: '',
  tanker: '',
  tractor: '',
  missing: null,
  observation: '',
})

const title = computed(() =>
  current.value
    ? t('documents.delivery.edit', { reference: current.value.reference })
    : t('documents.delivery.new'),
)

async function loadTrips() {
  trips.value = form.value.customer ? await fetchDeliverableTrips(Number(form.value.customer)) : []
}

async function onCustomerChange() {
  const customer = customers.value.find((c) => String(c.id) === form.value.customer)
  if (customer?.address && !form.value.delivery_address)
    form.value.delivery_address = customer.address
  form.value.lines = form.value.lines.filter((line) => !line.trip)
  await loadTrips()
}

const isPicked = (trip: DeliverableTrip) => form.value.lines.some((line) => line.trip === trip.trip)

function togglePick(trip: DeliverableTrip, picked: boolean) {
  if (picked && !isPicked(trip)) {
    form.value.lines = [
      ...form.value.lines,
      {
        trip: trip.trip,
        designation: trip.designation,
        quantity: trip.quantity,
        tanker: trip.tanker,
        tractor: trip.tractor,
        missing: trip.missing,
        observation: '',
      },
    ]
  } else if (!picked) {
    form.value.lines = form.value.lines.filter((line) => line.trip !== trip.trip)
  }
}

onMounted(async () => {
  try {
    const [all, note] = await Promise.all([
      listAll(createResourceApi<CustomerOption>('/customers/')),
      load(),
    ])
    customers.value = all
    if (note) {
      form.value = {
        customer: note.customer ? String(note.customer) : '',
        date: note.date,
        place: note.place,
        delivery_address: note.delivery_address,
        notes: note.notes,
        lines: note.lines.map((line) => ({ ...line })),
      }
      await loadTrips()
    }
  } catch {
    error.value = t('documents.common.loadError')
  }
})

function onSubmit() {
  const lines = form.value.lines.map((line) => ({
    trip: line.trip ?? null,
    designation: line.designation,
    quantity: line.quantity,
    tanker: line.tanker ?? '',
    tractor: line.tractor ?? '',
    missing: line.missing === '' ? null : (line.missing ?? null),
    observation: line.observation ?? '',
  })) as DeliveryNoteLine[]
  return save({
    customer: form.value.customer ? Number(form.value.customer) : null,
    date: form.value.date,
    place: form.value.place,
    delivery_address: form.value.delivery_address,
    notes: form.value.notes,
    lines,
  })
}
</script>

<template>
  <div class="max-w-5xl space-y-5">
    <DocumentFormHeader
      :title="title"
      :saved="!!current"
      :busy="busy"
      @pdf="pdf"
      @print="print"
      @back="back"
    />
    <AppAlert v-if="error" :message="error" />

    <form class="space-y-5" @submit.prevent="onSubmit">
      <section :class="CARD_CLASS" class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.delivery.customer') }}</span>
          <select
            v-model="form.customer"
            data-test="doc-customer"
            required
            :class="FIELD_CLASS"
            @change="onCustomerChange"
          >
            <option value="">{{ t('documents.delivery.selectCustomer') }}</option>
            <option v-for="c in customers" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
          </select>
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.common.date') }}</span>
          <input v-model="form.date" type="date" required :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.delivery.place') }}</span>
          <input v-model="form.place" type="text" placeholder="Bamako" :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.delivery.deliveryAddress') }}</span>
          <input
            id="delivery_address"
            v-model="form.delivery_address"
            type="text"
            :class="FIELD_CLASS"
          />
        </label>
      </section>

      <section v-if="form.customer" :class="CARD_CLASS">
        <div>
          <h2 class="font-semibold">{{ t('documents.delivery.tripsTitle') }}</h2>
          <p class="text-texte-3 text-xs">{{ t('documents.delivery.tripsHint') }}</p>
        </div>
        <p v-if="!trips.length" class="text-texte-3 text-sm">
          {{ t('documents.delivery.noTrips') }}
        </p>
        <ul v-else class="divide-ligne divide-y">
          <li v-for="trip in trips" :key="trip.trip">
            <label class="flex cursor-pointer flex-wrap items-center gap-x-4 gap-y-1 py-2 text-sm">
              <input
                type="checkbox"
                data-test="trip-pick"
                :checked="isPicked(trip)"
                @change="togglePick(trip, ($event.target as HTMLInputElement).checked)"
              />
              <span class="font-mono font-medium">{{ trip.reference }}</span>
              <span class="text-texte-2">{{ trip.loading_date }}</span>
              <span class="text-texte-2">{{ trip.tractor }} / {{ trip.tanker }}</span>
              <span class="font-mono">{{ formatQuantity(trip.quantity) }}</span>
              <span
                v-if="trip.other_notes.length"
                class="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800"
              >
                {{ t('documents.delivery.alreadyOn', { refs: trip.other_notes.join(', ') }) }}
              </span>
            </label>
          </li>
        </ul>
      </section>

      <section :class="CARD_CLASS">
        <h2 class="font-semibold">{{ t('documents.common.lines') }}</h2>
        <LinesTable
          v-model="form.lines"
          :columns="COLUMNS"
          :new-line="newLine"
          total-field="quantity"
        />
      </section>

      <section :class="CARD_CLASS">
        <label class="block space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.common.notes') }}</span>
          <textarea v-model="form.notes" rows="2" :class="FIELD_CLASS" class="h-auto py-2" />
        </label>
      </section>

      <div class="flex justify-end">
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('documents.common.saving') : t('documents.common.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>
