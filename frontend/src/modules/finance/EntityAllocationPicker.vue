<script setup lang="ts">
// Ergonomic replacement for raw content_type/object_id inputs on an Expense
// allocation line (guide Section 8.7: "a customs payment may affect several
// trips"): pick an entity kind, then search it by name/reference through
// the existing GET /search/ endpoint - no dedicated per-kind search
// endpoint needed. Resolving the picked kind to the numeric content_type
// ExpenseAllocationInputSerializer expects happens in the parent (see
// ExpenseForm.vue), not here - this component only ever deals in kinds.
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { searchGlobal } from '@/modules/search/api'
import type { SearchResults } from '@/modules/search/types'
import { ALLOCATABLE_KINDS } from './types'
import type { AllocatableKind } from './types'

export interface AllocationDraft {
  kind: AllocatableKind | ''
  objectId: number | null
  label: string
  allocatedAmount: string
}

const props = withDefaults(
  defineProps<{
    modelValue: AllocationDraft
    locked?: boolean
  }>(),
  { locked: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: AllocationDraft] }>()

const { t } = useI18n()

function update(patch: Partial<AllocationDraft>) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

function onKindChange(event: Event) {
  const kind = (event.target as HTMLSelectElement).value as AllocatableKind
  searchText.value = ''
  options.value = []
  update({ kind, objectId: null, label: '' })
}

interface SearchOption {
  id: number
  label: string
}

function extractOptions(kind: AllocatableKind, results: SearchResults): SearchOption[] {
  switch (kind) {
    case 'trip':
      return results.trips.map((r) => ({ id: r.id, label: r.reference }))
    case 'truck':
      return results.trucks.map((r) => ({
        id: r.id,
        label: `${r.internal_id} (${r.tractor_registration})`,
      }))
    case 'customer':
      return results.customers.map((r) => ({ id: r.id, label: r.name }))
    case 'supplier':
      return results.suppliers.map((r) => ({ id: r.id, label: r.name }))
    case 'transporter':
      return results.transporters.map((r) => ({ id: r.id, label: r.name }))
    default:
      return []
  }
}

const searchText = ref('')
const options = ref<SearchOption[]>([])
const searching = ref(false)
let debounceHandle: ReturnType<typeof setTimeout> | undefined

watch(searchText, (value) => {
  if (debounceHandle) clearTimeout(debounceHandle)
  const trimmed = value.trim()
  const kind = props.modelValue.kind
  if (!trimmed || !kind) {
    options.value = []
    return
  }
  debounceHandle = setTimeout(async () => {
    searching.value = true
    try {
      options.value = extractOptions(kind, await searchGlobal(trimmed))
    } finally {
      searching.value = false
    }
  }, 300)
})

function selectOption(option: SearchOption) {
  update({ objectId: option.id, label: option.label })
  searchText.value = ''
  options.value = []
}

function clearSelection() {
  update({ objectId: null, label: '' })
}

const hasSelection = computed(() => props.modelValue.objectId !== null)
</script>

<template>
  <div class="flex flex-wrap items-start gap-2">
    <select
      :value="modelValue.kind"
      :disabled="locked"
      class="border-ligne-forte h-12 w-36 rounded-lg border bg-white px-3 text-sm disabled:bg-sable"
      @change="onKindChange"
    >
      <option value="" disabled>{{ t('finance.expense.pickKind') }}</option>
      <option v-for="kind in ALLOCATABLE_KINDS" :key="kind" :value="kind">
        {{ t(`finance.allocationKind.${kind}`) }}
      </option>
    </select>

    <div class="relative w-56">
      <div
        v-if="hasSelection"
        class="border-ligne-forte flex h-12 items-center justify-between rounded-lg border bg-sable px-3 text-sm"
      >
        <span class="text-texte truncate font-medium">{{ modelValue.label }}</span>
        <button
          v-if="!locked"
          type="button"
          class="text-texte-2 hover:text-critique ms-2"
          @click="clearSelection"
        >
          {{ t('finance.expense.changeSelection') }}
        </button>
      </div>
      <template v-else>
        <input
          v-model="searchText"
          type="text"
          :disabled="!modelValue.kind"
          :placeholder="t('finance.expense.searchEntity')"
          class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 text-sm disabled:bg-sable"
        />
        <div
          v-if="searchText.trim()"
          class="border-ligne absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-lg border bg-white shadow-lg"
        >
          <p v-if="searching" class="text-texte-3 px-3 py-2 text-sm">{{ t('search.searching') }}</p>
          <template v-else>
            <button
              v-for="option in options"
              :key="option.id"
              type="button"
              class="hover:bg-sable block w-full px-3 py-2 text-start text-sm"
              @click="selectOption(option)"
            >
              {{ option.label }}
            </button>
            <p v-if="!options.length" class="text-texte-3 px-3 py-2 text-sm">
              {{ t('search.noResults') }}
            </p>
          </template>
        </div>
      </template>
    </div>

    <input
      :value="modelValue.allocatedAmount"
      type="number"
      step="0.01"
      min="0.01"
      :placeholder="t('finance.expense.amountPlaceholder')"
      class="border-ligne-forte h-12 w-32 rounded-lg border bg-white px-3.5 text-sm"
      @input="update({ allocatedAmount: ($event.target as HTMLInputElement).value })"
    />
  </div>
</template>
