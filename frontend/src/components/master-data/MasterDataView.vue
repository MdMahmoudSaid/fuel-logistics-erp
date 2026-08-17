<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import DataTable from './DataTable.vue'
import EntityForm from './EntityForm.vue'
import type { FieldSchema } from './types'
import type { ResourceApi } from '@/api/resource'

const props = defineProps<{
  title: string
  resource: ResourceApi<Record<string, unknown>>
  fields: FieldSchema[]
}>()

const rows = ref<Record<string, unknown>[]>([])
const showForm = ref(false)
const editingId = ref<number | null>(null)
const formValue = ref<Record<string, unknown>>({})
const error = ref('')

const columns = computed(() =>
  props.fields
    .filter((f) => f.type !== 'textarea' && f.type !== 'password')
    .map((f) => ({ key: f.key, label: f.label })),
)

async function load() {
  const data = await props.resource.list()
  // Copy defensively: some resource implementations (and this component's
  // own test doubles) return the same array reference across calls and
  // mutate it in place, which Vue's ref would otherwise treat as an
  // unchanged value and skip re-rendering.
  rows.value = [...data.results]
}

function openCreate() {
  editingId.value = null
  formValue.value = {}
  showForm.value = true
  error.value = ''
}

function openEdit(row: Record<string, unknown>) {
  editingId.value = row.id as number
  formValue.value = { ...row }
  showForm.value = true
  error.value = ''
}

async function onSubmit() {
  try {
    if (editingId.value === null) {
      await props.resource.create(formValue.value)
    } else {
      await props.resource.update(editingId.value, formValue.value)
    }
    showForm.value = false
    await load()
  } catch {
    error.value = 'Could not save — check the fields and your permissions.'
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">{{ title }}</h2>
      <button class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white" @click="openCreate">
        Add
      </button>
    </div>

    <div class="rounded border bg-white">
      <DataTable :columns="columns" :rows="rows" @edit="openEdit" />
    </div>

    <div v-if="showForm" class="fixed inset-0 flex items-center justify-center bg-black/30">
      <div class="w-full max-w-md rounded-lg bg-white p-6 shadow-lg">
        <h3 class="mb-4 text-base font-semibold text-slate-800">
          {{ editingId === null ? 'New' : 'Edit' }} {{ title }}
        </h3>
        <p v-if="error" class="mb-2 text-sm text-red-600">{{ error }}</p>
        <EntityForm v-model="formValue" :fields="fields" @submit="onSubmit" @cancel="showForm = false" />
      </div>
    </div>
  </div>
</template>
