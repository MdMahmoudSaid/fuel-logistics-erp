<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { MODULES, ACTIONS } from './permissionSchema'
import Button from '@/components/ui/Button.vue'

const { t } = useI18n()

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
  const next = current.includes(action) ? current.filter((a) => a !== action) : [...current, action]
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
    <div class="space-y-1.5">
      <label class="text-texte-2 text-sm font-medium" for="role-name">{{ t('roles.name') }}</label>
      <input
        id="role-name"
        :value="modelValue.name"
        required
        class="border-ligne-forte h-12 w-full rounded-lg border bg-white px-3.5 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        @input="setName(($event.target as HTMLInputElement).value)"
      />
    </div>

    <!-- Téléphone : un bloc par module, cases à cocher étiquetées. -->
    <div class="border-ligne divide-ligne divide-y rounded-xl border md:hidden">
      <div v-for="module in MODULES" :key="`m-${module}`" class="p-3">
        <p class="text-texte mb-2 text-sm font-medium">{{ t(`roles.modules.${module}`) }}</p>
        <div class="grid grid-cols-2 gap-x-3 gap-y-1">
          <label
            v-for="action in ACTIONS"
            :key="action"
            class="text-texte-2 flex h-10 items-center gap-2 text-sm"
          >
            <input
              type="checkbox"
              class="border-ligne-forte accent-orange h-5 w-5 rounded"
              :checked="isChecked(module, action)"
              @change="toggle(module, action)"
            />
            {{ t(`roles.actions.${action}`) }}
          </label>
        </div>
      </div>
    </div>

    <div class="border-ligne hidden overflow-x-auto rounded-xl border md:block">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="px-3 py-2.5 font-medium">{{ t('roles.module') }}</th>
            <th v-for="action in ACTIONS" :key="action" class="px-3 py-2.5 font-medium">
              {{ t(`roles.actions.${action}`) }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="module in MODULES" :key="module" class="border-ligne border-b last:border-0">
            <td class="px-3 py-2.5">{{ t(`roles.modules.${module}`) }}</td>
            <td v-for="action in ACTIONS" :key="action" class="px-3 py-2.5 text-center">
              <input
                type="checkbox"
                class="border-ligne-forte accent-orange h-4 w-4 rounded"
                :checked="isChecked(module, action)"
                @change="toggle(module, action)"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="flex justify-end gap-2 pt-2">
      <Button type="button" variant="ghost" @click="$emit('cancel')">{{
        t('common.cancel')
      }}</Button>
      <Button type="submit" variant="primary">{{ t('common.save') }}</Button>
    </div>
  </form>
</template>
