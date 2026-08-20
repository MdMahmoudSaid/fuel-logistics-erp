<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import RoleFormModal from './RoleFormModal.vue'
import { createResourceApi } from '@/api/resource'
import Button from '@/components/ui/Button.vue'

const { t } = useI18n()

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
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">{{ t('roles.title') }}</h1>
      <Button variant="primary" @click="openCreate">{{ t('roles.add') }}</Button>
    </div>

    <div class="border-ligne overflow-x-auto rounded-xl border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">{{ t('roles.name') }}</th>
            <th class="px-3 py-2.5" />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="role in roles"
            :key="role.id"
            class="border-ligne hover:bg-sable border-b last:border-0"
          >
            <td class="px-3 py-2.5">{{ role.name }}</td>
            <td class="px-3 py-2.5 text-right">
              <button class="text-texte-2 hover:text-texte" @click="openEdit(role)">
                {{ t('roles.edit') }}
              </button>
            </td>
          </tr>
          <tr v-if="roles.length === 0">
            <td colspan="2" class="text-texte-3 px-3 py-8 text-center">{{ t('roles.noRoles') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="showForm" class="fixed inset-0 z-30 flex items-center justify-center bg-black/40">
      <div class="bg-surface border-ligne w-full max-w-lg rounded-xl border p-6">
        <h2 class="font-display mb-4 text-lg leading-none font-semibold uppercase">
          {{ editingId === null ? t('roles.newRole') : t('roles.editRole') }}
        </h2>
        <RoleFormModal v-model="formValue" @submit="onSubmit" @cancel="showForm = false" />
      </div>
    </div>
  </div>
</template>
