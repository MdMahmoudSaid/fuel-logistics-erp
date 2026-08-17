<script setup lang="ts">
defineProps<{
  columns: { key: string; label: string }[]
  rows: Record<string, unknown>[]
}>()

defineEmits<{ edit: [row: Record<string, unknown>] }>()
</script>

<template>
  <table class="w-full text-left text-sm">
    <thead>
      <tr class="border-b text-slate-500">
        <th v-for="col in columns" :key="col.key" class="px-3 py-2 font-medium">{{ col.label }}</th>
        <th class="px-3 py-2" />
      </tr>
    </thead>
    <tbody>
      <tr v-for="row in rows" :key="String(row.id)" class="border-b last:border-0 hover:bg-slate-50">
        <td v-for="col in columns" :key="col.key" class="px-3 py-2">{{ row[col.key] }}</td>
        <td class="px-3 py-2 text-right">
          <button class="text-slate-500 hover:text-slate-800" @click="$emit('edit', row)">Edit</button>
        </td>
      </tr>
      <tr v-if="rows.length === 0">
        <td :colspan="columns.length + 1" class="px-3 py-6 text-center text-slate-400">
          No records yet.
        </td>
      </tr>
    </tbody>
  </table>
</template>
