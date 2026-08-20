<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import DataTable from './DataTable.vue'
import EntityForm from './EntityForm.vue'
import Button from '@/components/ui/Button.vue'
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

async function onDelete(row: Record<string, unknown>) {
  if (!window.confirm('Are you sure you want to delete this record?')) {
    return
  }
  try {
    await props.resource.remove(row.id as number)
    await load()
  } catch {
    error.value = 'Could not delete — check your permissions.'
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">{{ title }}</h1>
      <Button variant="primary" @click="openCreate">Add</Button>
    </div>

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <DataTable :columns="columns" :rows="rows" @edit="openEdit" @delete="onDelete" />
    </div>

    <div v-if="showForm" class="fixed inset-0 z-30 flex items-center justify-center bg-black/40">
      <div class="bg-surface border-ligne w-full max-w-md rounded-xl border p-6">
        <h2 class="font-display mb-4 text-lg leading-none font-semibold uppercase">
          {{ editingId === null ? 'New' : 'Edit' }} {{ title }}
        </h2>
        <p v-if="error" class="text-critique mb-2 text-sm">{{ error }}</p>
        <EntityForm
          v-model="formValue"
          :fields="fields"
          @submit="onSubmit"
          @cancel="showForm = false"
        />
      </div>
    </div>
  </div>
</template>
