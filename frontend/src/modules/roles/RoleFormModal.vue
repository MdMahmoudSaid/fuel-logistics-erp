<script setup lang="ts">
import { MODULES, ACTIONS } from './permissionSchema'

const props = defineProps<{
  modelValue: { name: string; permissions: Record<string, string[]> }
}>()
const emit = defineEmits<{
  'update:modelValue': [value: { name: string; permissions: Record<string, string[]> }]
  submit: []
  cancel: []
}>()

function isChecked(module: string, action: string) {
  return (props.modelValue.permissions[module] ?? []).includes(action)
}

function toggle(module: string, action: string) {
  const current = props.modelValue.permissions[module] ?? []
  const next = current.includes(action)
    ? current.filter((a) => a !== action)
    : [...current, action]
  emit('update:modelValue', {
    ...props.modelValue,
    permissions: { ...props.modelValue.permissions, [module]: next },
  })
}

function setName(value: string) {
  emit('update:modelValue', { ...props.modelValue, name: value })
}
</script>

<template>
  <form class="space-y-4" @submit.prevent="$emit('submit')">
    <div class="space-y-1">
      <label class="text-sm font-medium text-slate-600" for="role-name">Name</label>
      <input
        id="role-name"
        :value="modelValue.name"
        required
        class="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        @input="setName(($event.target as HTMLInputElement).value)"
      />
    </div>

    <table class="w-full text-left text-sm">
      <thead>
        <tr class="border-b text-slate-500">
          <th class="px-2 py-1 font-medium">Module</th>
          <th v-for="action in ACTIONS" :key="action" class="px-2 py-1 font-medium capitalize">
            {{ action }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="module in MODULES" :key="module" class="border-b last:border-0">
          <td class="px-2 py-1 capitalize">{{ module }}</td>
          <td v-for="action in ACTIONS" :key="action" class="px-2 py-1 text-center">
            <input
              type="checkbox"
              :checked="isChecked(module, action)"
              @change="toggle(module, action)"
            />
          </td>
        </tr>
      </tbody>
    </table>

    <div class="flex justify-end gap-2 pt-2">
      <button type="button" class="px-3 py-2 text-sm text-slate-500" @click="$emit('cancel')">
        Cancel
      </button>
      <button type="submit" class="rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white">
        Save
      </button>
    </div>
  </form>
</template>
