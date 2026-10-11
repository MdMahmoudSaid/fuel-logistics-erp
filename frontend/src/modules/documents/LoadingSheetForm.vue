<script setup lang="ts">
// Loading sheet (spec 2026-10-11 documents-commerciaux §5): step 1 asks the
// details the depot needs, step 2 picks the trucks from the fleet.
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { createResourceApi } from '@/api/resource'
import AppAlert from '@/components/ui/AppAlert.vue'
import Button from '@/components/ui/Button.vue'
import { fetchCompanyProfile } from '@/modules/settings/api'
import { formatQuantity } from '@/utils/currency'
import DocumentFormHeader from './DocumentFormHeader.vue'
import LinesTable from './LinesTable.vue'
import { listAll } from './api'
import type { LineColumn } from './LinesTable.vue'
import type { LoadingSheet, LoadingSheetLine } from './types'
import { CARD_CLASS, FIELD_CLASS, LABEL_CLASS, today, useDocumentForm } from './useDocumentForm'

interface TruckOption {
  id: number
  internal_id: string
  tractor_registration: string
  tanker_registration: string
  capacity_litres: string
}

const { t } = useI18n()
const { current, saving, busy, error, load, save, pdf, print, back } =
  useDocumentForm<LoadingSheet>('loading')

const step = ref<1 | 2>(1)
const suppliers = ref<{ id: number; name: string }[]>([])
const trucks = ref<TruckOption[]>([])
const search = ref('')
const form = ref({
  supplier: '',
  supplier_name: '',
  date: today(),
  on_behalf_of: '',
  source_reference: '',
  product_name: 'GASOIL',
  route: '',
  notes: '',
  lines: [] as Record<string, unknown>[],
})

const COLUMNS: LineColumn[] = [
  { field: 'tractor', labelKey: 'documents.lines.tractor' },
  { field: 'tanker', labelKey: 'documents.lines.tanker' },
  { field: 'capacity_litres', labelKey: 'documents.lines.capacity', type: 'number' },
  { field: 'product_name', labelKey: 'documents.lines.product' },
  { field: 'be_number', labelKey: 'documents.lines.be' },
  { field: 'route', labelKey: 'documents.lines.route' },
]
const newLine = (): Record<string, unknown> => ({
  truck: null,
  tractor: '',
  tanker: '',
  capacity_litres: '',
  product_name: form.value.product_name,
  be_number: '',
  route: form.value.route,
})

const title = computed(() =>
  current.value
    ? t('documents.loading.edit', { reference: current.value.reference })
    : t('documents.loading.new'),
)
const filteredTrucks = computed(() => {
  const q = search.value.trim().toLowerCase()
  return trucks.value.filter((truck) =>
    `${truck.internal_id} ${truck.tractor_registration} ${truck.tanker_registration}`
      .toLowerCase()
      .includes(q),
  )
})
const totalLitres = computed(() =>
  form.value.lines.reduce((sum, line) => sum + (Number(line.capacity_litres) || 0), 0),
)

const isPicked = (truck: TruckOption) => form.value.lines.some((line) => line.truck === truck.id)

function togglePick(truck: TruckOption, picked: boolean) {
  if (picked && !isPicked(truck)) {
    form.value.lines = [
      ...form.value.lines,
      {
        ...newLine(),
        truck: truck.id,
        tractor: truck.tractor_registration,
        tanker: truck.tanker_registration,
        capacity_litres: truck.capacity_litres,
      },
    ]
  } else if (!picked) {
    form.value.lines = form.value.lines.filter((line) => line.truck !== truck.id)
  }
}

onMounted(async () => {
  try {
    // Trucks belong to the operations module: a role without it can still
    // write the lines by hand.
    listAll(createResourceApi<TruckOption>('/trucks/'), { is_active: true })
      .then((all) => (trucks.value = all))
      .catch(() => (trucks.value = []))
    const [allSuppliers, sheet] = await Promise.all([
      listAll(createResourceApi<{ id: number; name: string }>('/suppliers/')),
      load(),
    ])
    suppliers.value = allSuppliers
    if (sheet) {
      form.value = {
        supplier: sheet.supplier ? String(sheet.supplier) : '',
        supplier_name: sheet.supplier_name,
        date: sheet.date,
        on_behalf_of: sheet.on_behalf_of,
        source_reference: sheet.source_reference,
        product_name: sheet.product_name,
        route: sheet.route,
        notes: sheet.notes,
        lines: sheet.lines.map((line) => ({ ...line })),
      }
      step.value = 2
    } else {
      form.value.on_behalf_of = (await fetchCompanyProfile().catch(() => null))?.name ?? ''
    }
  } catch {
    error.value = t('documents.common.loadError')
  }
})

function onSubmit() {
  const lines = form.value.lines.map((line) => ({
    truck: line.truck ?? null,
    tractor: line.tractor ?? '',
    tanker: line.tanker ?? '',
    capacity_litres: line.capacity_litres,
    product_name: line.product_name ?? '',
    be_number: line.be_number ?? '',
    route: line.route ?? '',
  })) as LoadingSheetLine[]
  return save({
    supplier: form.value.supplier ? Number(form.value.supplier) : null,
    supplier_name: form.value.supplier ? '' : form.value.supplier_name,
    date: form.value.date,
    on_behalf_of: form.value.on_behalf_of,
    source_reference: form.value.source_reference,
    product_name: form.value.product_name,
    route: form.value.route,
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

    <div class="flex gap-2 text-sm">
      <button
        type="button"
        class="rounded-full px-3 py-1"
        :class="step === 1 ? 'bg-bitume text-white' : 'bg-sable'"
        @click="step = 1"
      >
        {{ t('documents.loading.stepInfo') }}
      </button>
      <button
        type="button"
        class="rounded-full px-3 py-1"
        :class="step === 2 ? 'bg-bitume text-white' : 'bg-sable'"
        :disabled="!form.supplier && !form.supplier_name"
        @click="step = 2"
      >
        {{ t('documents.loading.stepTrucks') }}
      </button>
    </div>

    <form class="space-y-5" @submit.prevent="onSubmit">
      <section v-show="step === 1" :class="CARD_CLASS" class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.loading.supplier') }}</span>
          <select v-model="form.supplier" :class="FIELD_CLASS">
            <option value="">{{ t('documents.loading.otherSupplier') }}</option>
            <option v-for="s in suppliers" :key="s.id" :value="String(s.id)">{{ s.name }}</option>
          </select>
        </label>
        <label v-if="!form.supplier" class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.loading.supplierName') }}</span>
          <input id="supplier_name" v-model="form.supplier_name" type="text" :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.common.date') }}</span>
          <input v-model="form.date" type="date" required :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.loading.onBehalfOf') }}</span>
          <input id="on_behalf_of" v-model="form.on_behalf_of" type="text" :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.loading.sourceReference') }}</span>
          <input v-model="form.source_reference" type="text" :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.loading.productName') }}</span>
          <input id="product_name" v-model="form.product_name" type="text" :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5">
          <span :class="LABEL_CLASS">{{ t('documents.loading.route') }}</span>
          <input id="route" v-model="form.route" type="text" :class="FIELD_CLASS" />
        </label>
        <label class="space-y-1.5 sm:col-span-2">
          <span :class="LABEL_CLASS">{{ t('documents.common.notes') }}</span>
          <textarea v-model="form.notes" rows="2" :class="FIELD_CLASS" class="h-auto py-2" />
        </label>
        <div class="flex justify-end sm:col-span-2">
          <Button
            type="button"
            variant="primary"
            data-test="loading-next"
            :disabled="!form.supplier && !form.supplier_name"
            @click="step = 2"
          >
            {{ t('documents.loading.next') }}
          </Button>
        </div>
      </section>

      <template v-if="step === 2">
        <section :class="CARD_CLASS">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h2 class="font-semibold">{{ t('documents.loading.stepTrucks') }}</h2>
            <span class="text-texte-2 text-sm">
              {{
                t('documents.loading.trucksCount', {
                  count: form.lines.length,
                  litres: formatQuantity(totalLitres),
                })
              }}
            </span>
          </div>
          <input
            v-model="search"
            type="search"
            :placeholder="t('documents.loading.searchTrucks')"
            :class="FIELD_CLASS"
          />
          <p v-if="!trucks.length" class="text-texte-3 text-sm">
            {{ t('documents.loading.noTrucks') }}
          </p>
          <ul v-else class="grid max-h-72 gap-1 overflow-y-auto sm:grid-cols-2">
            <li v-for="truck in filteredTrucks" :key="truck.id">
              <label
                class="border-ligne hover:bg-sable flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-sm"
              >
                <input
                  type="checkbox"
                  data-test="truck-pick"
                  :checked="isPicked(truck)"
                  @change="togglePick(truck, ($event.target as HTMLInputElement).checked)"
                />
                <span class="font-mono">{{ truck.tractor_registration }}</span>
                <span class="text-texte-2 font-mono">{{ truck.tanker_registration }}</span>
                <span class="ms-auto font-mono">{{ formatQuantity(truck.capacity_litres) }}</span>
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
            total-field="capacity_litres"
          />
        </section>

        <div class="flex justify-end">
          <Button type="submit" variant="primary" :loading="saving">
            {{ saving ? t('documents.common.saving') : t('documents.common.save') }}
          </Button>
        </div>
      </template>
    </form>
  </div>
</template>
