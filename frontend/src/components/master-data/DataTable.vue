<script setup lang="ts">
defineProps<{
  columns: { key: string; label: string }[]
  rows: Record<string, unknown>[]
}>()

defineEmits<{ edit: [row: Record<string, unknown>]; delete: [row: Record<string, unknown>] }>()
</script>

<template>
  <table class="w-full text-left text-sm">
    <thead>
      <tr class="border-ligne text-texte-2 border-b">
        <th v-for="col in columns" :key="col.key" class="px-3 py-2.5 font-medium">
          {{ col.label }}
        </th>
        <th class="px-3 py-2.5" />
      </tr>
    </thead>
    <tbody>
      <tr
        v-for="row in rows"
        :key="String(row.id)"
        class="border-ligne hover:bg-sable border-b last:border-0"
      >
        <td v-for="col in columns" :key="col.key" class="px-3 py-2.5">{{ row[col.key] }}</td>
        <td class="px-3 py-2.5 text-right whitespace-nowrap">
          <button class="text-texte-2 hover:text-texte" @click="$emit('edit', row)">Edit</button>
          <button class="text-critique ml-3 hover:brightness-90" @click="$emit('delete', row)">
            Delete
          </button>
        </td>
      </tr>
      <tr v-if="rows.length === 0">
        <td :colspan="columns.length + 1" class="text-texte-3 px-3 py-8 text-center">
          No records yet.
        </td>
      </tr>
    </tbody>
  </table>
</template>
