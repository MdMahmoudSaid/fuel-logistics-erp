<script setup lang="ts">
// docs/PHASE_6_PLAN.md Etape 8: admin interface to inspect entity
// modifications with a diff view highlighting changed values.
import { ref, onMounted } from 'vue'
import { auditLogResource } from './api'
import type { AuditLog } from './types'
import Badge from '@/components/ui/Badge.vue'
import MonoValue from '@/components/ui/MonoValue.vue'

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

function badgeVariant(action: string) {
  if (action === 'CREATE') return 'livre' as const
  if (action === 'UPDATE') return 'transit' as const
  if (action === 'DELETE') return 'critique' as const
  if (action === 'CANCEL' || action === 'REVERSE') return 'ecart' as const
  return 'neutre' as const
}
</script>

<template>
  <div class="max-w-5xl space-y-6">
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">Audit Log</h1>

    <p v-if="error" class="text-critique text-sm">{{ error }}</p>
    <p v-else-if="loading" class="text-texte-3 text-sm">Loading…</p>

    <section v-else class="border-ligne overflow-auto rounded-xl border bg-white">
      <table class="w-full text-left text-sm">
        <thead>
          <tr class="border-ligne text-texte-2 border-b">
            <th class="font-display px-3 py-2.5 text-xs font-medium tracking-wide uppercase">
              Timestamp
            </th>
            <th class="font-display px-3 py-2.5 text-xs font-medium tracking-wide uppercase">
              Action
            </th>
            <th class="font-display px-3 py-2.5 text-xs font-medium tracking-wide uppercase">
              Entity
            </th>
            <th class="font-display px-3 py-2.5 text-xs font-medium tracking-wide uppercase">
              Object ID
            </th>
            <th class="font-display px-3 py-2.5 text-xs font-medium tracking-wide uppercase">
              User
            </th>
            <th class="px-3 py-2.5"></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="log in logs" :key="log.id">
            <tr
              class="border-ligne hover:bg-sable cursor-pointer border-b last:border-0"
              @click="toggle(log.id)"
            >
              <td class="px-3 py-2.5">
                <MonoValue :value="new Date(log.timestamp).toLocaleString()" align="left" />
              </td>
              <td class="px-3 py-2.5">
                <Badge :variant="badgeVariant(log.action)">{{ log.action }}</Badge>
              </td>
              <td class="px-3 py-2.5">{{ log.content_type_label }}</td>
              <td class="px-3 py-2.5"><MonoValue :value="log.object_id" align="left" /></td>
              <td class="px-3 py-2.5">{{ log.user_email || '—' }}</td>
              <td class="text-texte-3 px-3 py-2.5">{{ expandedId === log.id ? '▲' : '▼' }}</td>
            </tr>
            <tr v-if="expandedId === log.id" class="border-ligne bg-sable border-b last:border-0">
              <td colspan="6" class="px-4 py-3">
                <p v-if="diffKeys(log).length === 0" class="text-texte-3 text-xs">
                  No field-level changes recorded.
                </p>
                <table v-else class="w-full text-xs">
                  <thead>
                    <tr class="text-texte-3">
                      <th class="py-1 text-left font-medium">Field</th>
                      <th class="py-1 text-left font-medium">Previous</th>
                      <th class="py-1 text-left font-medium">New</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="key in diffKeys(log)" :key="key">
                      <td class="text-texte-2 py-1 pr-4 font-medium">{{ key }}</td>
                      <td class="text-critique py-1 pr-4 line-through">
                        {{ formatValue(log.previous_value?.[key]) }}
                      </td>
                      <td class="text-livre-texte py-1">{{ formatValue(log.new_value?.[key]) }}</td>
                    </tr>
                  </tbody>
                </table>
                <p v-if="log.reason" class="text-texte-2 mt-2 text-xs">Reason: {{ log.reason }}</p>
              </td>
            </tr>
          </template>
          <tr v-if="logs.length === 0">
            <td colspan="6" class="text-texte-3 px-3 py-8 text-center">No audit entries yet.</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
