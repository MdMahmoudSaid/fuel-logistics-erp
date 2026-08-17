<script setup lang="ts">
import { ref, onMounted } from 'vue'
import RoleFormModal from './RoleFormModal.vue'
import { createResourceApi } from '@/api/resource'

interface RoleRecord {
  id: number
  name: string
  permissions: Record<string, string[]>
}

const resource = createResourceApi<RoleRecord>('/accounts/roles/')
const roles = ref<RoleRecord[]>([])
const showForm = ref(false)
const editingId = ref<number | null>(null)
const formValue = ref<{ name: string; permissions: Record<string, string[]> }>({
  name: '',
  permissions: {},
})

async function load() {
  const data = await resource.list()
  roles.value = data.results
}

function openCreate() {
  editingId.value = null
  formValue.value = { name: '', permissions: {} }
  showForm.value = true
}

function openEdit(role: RoleRecord) {
  editingId.value = role.id
  formValue.value = { name: role.name, permissions: role.permissions }
  showForm.value = true
}

async function onSubmit() {
  if (editingId.value === null) {
    await resource.create(formValue.value)
  } else {
    await resource.update(editingId.value, formValue.value)
  }
  showForm.value = false
  await load()
}

onMounted(load)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-slate-800">Roles</h2>
      <button class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white" @click="openCreate">
        Add
      </button>
    </div>

    <ul class="divide-y rounded border bg-white">
      <li v-for="role in roles" :key="role.id" class="flex items-center justify-between px-3 py-2 text-sm">
        <span>{{ role.name }}</span>
        <button class="text-slate-500 hover:text-slate-800" @click="openEdit(role)">Edit</button>
      </li>
    </ul>

    <div v-if="showForm" class="fixed inset-0 flex items-center justify-center bg-black/30">
      <div class="w-full max-w-lg rounded-lg bg-white p-6 shadow-lg">
        <h3 class="mb-4 text-base font-semibold text-slate-800">
          {{ editingId === null ? 'New' : 'Edit' }} Role
        </h3>
        <RoleFormModal v-model="formValue" @submit="onSubmit" @cancel="showForm = false" />
      </div>
    </div>
  </div>
</template>
