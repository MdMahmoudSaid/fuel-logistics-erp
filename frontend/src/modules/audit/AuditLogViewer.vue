<script setup lang="ts">
// docs/PHASE_6_PLAN.md Etape 8: admin interface to inspect entity
// modifications with a diff view highlighting changed values.
import { ref, onMounted } from 'vue'
import { auditLogResource } from './api'
import type { AuditLog } from './types'

const logs = ref<AuditLog[]>([])
const loading = ref(true)
const error = ref('')
const expandedId = ref<number | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await auditLogResource.list()
    logs.value = data.results
  } catch {
    error.value = 'Could not load the audit log.'
  } finally {
    loading.value = false
  }
}

onMounted(load)

function toggle(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

// Only the fields that actually differ between before/after are worth a
// row - previous_value/new_value are full object snapshots (see
// apps/audit/services.py build_snapshot()), not a pre-computed diff.
function diffKeys(log: AuditLog): string[] {
  const prev = log.previous_value ?? {}
  const next = log.new_value ?? {}
  const keys = new Set([...Object.keys(prev), ...Object.keys(next)])
  return [...keys].filter((key) => JSON.stringify(prev[key]) !== JSON.stringify(next[key]))
}

function formatValue(value: unknown): string {
  return value === null || value === undefined ? '—' : String(value)
}

const ACTION_BADGE: Record<string, string> = {
  CREATE: 'bg-emerald-100 text-emerald-700',
  UPDATE: 'bg-sky-100 text-sky-700',
  DELETE: 'bg-red-100 text-red-700',
  CANCEL: 'bg-amber-100 text-amber-700',
  REVERSE: 'bg-purple-100 text-purple-700',
}
</script>

<template>
  <div class="max-w-5xl space-y-6">
    <h2 class="text-lg font-semibold text-slate-800">Audit Log</h2>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-else-if="loading" class="text-sm text-slate-400">Loading…</p>

    <section v-else class="overflow-auto rounded border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-b text-slate-500">
            <th class="px-2 py-1.5 font-medium">Timestamp</th>
            <th class="px-2 py-1.5 font-medium">Action</th>
            <th class="px-2 py-1.5 font-medium">Entity</th>
            <th class="px-2 py-1.5 font-medium">Object ID</th>
            <th class="px-2 py-1.5 font-medium">User</th>
            <th class="px-2 py-1.5"></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="log in logs" :key="log.id">
            <tr
              class="cursor-pointer border-b last:border-0 hover:bg-slate-50"
              @click="toggle(log.id)"
            >
              <td class="px-2 py-1.5">{{ new Date(log.timestamp).toLocaleString() }}</td>
              <td class="px-2 py-1.5">
                <span
                  class="rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="ACTION_BADGE[log.action]"
                >
                  {{ log.action }}
                </span>
              </td>
              <td class="px-2 py-1.5">{{ log.content_type_label }}</td>
              <td class="px-2 py-1.5">{{ log.object_id }}</td>
              <td class="px-2 py-1.5">{{ log.user_email || '—' }}</td>
              <td class="px-2 py-1.5 text-slate-400">{{ expandedId === log.id ? '▲' : '▼' }}</td>
            </tr>
            <tr v-if="expandedId === log.id" class="border-b bg-slate-50 last:border-0">
              <td colspan="6" class="px-4 py-3">
                <p v-if="diffKeys(log).length === 0" class="text-xs text-slate-400">
                  No field-level changes recorded.
                </p>
                <table v-else class="w-full text-xs">
                  <thead>
                    <tr class="text-slate-400">
                      <th class="py-1 text-left font-medium">Field</th>
                      <th class="py-1 text-left font-medium">Previous</th>
                      <th class="py-1 text-left font-medium">New</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="key in diffKeys(log)" :key="key">
                      <td class="py-1 pr-4 font-medium text-slate-600">{{ key }}</td>
                      <td class="py-1 pr-4 text-red-600 line-through">
                        {{ formatValue(log.previous_value?.[key]) }}
                      </td>
                      <td class="py-1 text-emerald-700">{{ formatValue(log.new_value?.[key]) }}</td>
                    </tr>
                  </tbody>
                </table>
                <p v-if="log.reason" class="mt-2 text-xs text-slate-500">
                  Reason: {{ log.reason }}
                </p>
              </td>
            </tr>
          </template>
          <tr v-if="logs.length === 0">
            <td colspan="6" class="px-2 py-4 text-center text-slate-400">No audit entries yet.</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
